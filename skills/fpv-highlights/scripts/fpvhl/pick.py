"""Pick: score every 0.1 s of every recording, choose the best non-repetitive clips up to --length seconds.

Interest per sample (each feature divided by its session-wide 90th percentile over flying samples,
capped at 3, so the session's own typical flying = about 1):

    0.8 speed + 1.2 roll + 0.6 zoom + 1.2 parallax        smoothed over 0.5 s

A clip window is refused when the picture is bad (static/noise, black, blown out), when the quad is
still for more than 0.6 s inside it (parked, menu, crash), or in the first/last second of a recording.
Window score = mean interest + 0.25 x peak. Clips are taken greedily, best first, with at most
--per-video clips per recording, 3 s apart, and a colour-histogram check so one view isn't repeated.
Recordings are grouped into scenes (same place: mean colour histogram over the recording) and at
most --per-scene clips come from one scene; the cap is raised only when the length can't be filled.
Each accepted clip then grows by up to 0.6 x --clip while the action carries on at its edges."""
import json
import re
from pathlib import Path

import numpy as np
import cv2

from .scan import SAMPLE_HZ

W = dict(speed=0.8, roll=1.2, zoom=0.6, parallax=1.2)
STILL_DIFF = 3.0          # mean |frame diff| at 160x90 below this = nothing moving (sensor noise is ~1.5-2.5)
STILL_RUN_S = 0.6
OSD_TEXT = 0.012          # static centre text above this (1 s mean) = STATS screen / warnings / menu
EDGE_S = 1.0
MIN_GAP_S = 3.0
SAME_VIEW = 0.985         # cosine of HSV histograms above this = same view as a clip already taken
SAME_SCENE = 0.95         # cosine of two recordings' mean histograms above this = same place (backyard, room)


def load(work, good):
    vids = {}
    for name, path in sorted(good.items()):
        with np.load(Path(work) / "scan" / f"{name}.npz") as z:
            vids[name] = dict(path=str(path), fps=float(z["fps"]), step=int(z["step"]), feats=z["feats"],
                              audio=z["audio"], thumbs=z["thumbs"], dt=int(z["step"]) / float(z["fps"]))
    return vids


def scenes(vids):
    """Group recordings by place: mean HSV histogram of each recording's 1 Hz thumbnails, then
    average-linkage clustering (merge the two most similar groups while their mean similarity is at
    least SAME_SCENE). Sets v['scene'] and returns the number of scenes."""
    names = list(vids)
    H = []
    for name in names:
        th = vids[name]["thumbs"]
        h = np.mean([_hist(t) for t in th[:: max(1, len(th) // 40)]], axis=0)
        H.append(h / (np.linalg.norm(h) + 1e-9))
    S = np.array(H) @ np.array(H).T
    groups = [[i] for i in range(len(names))]
    while len(groups) > 1:
        best, pair = -1.0, None
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                m = float(S[np.ix_(groups[i], groups[j])].mean())
                if m > best:
                    best, pair = m, (i, j)
        if best < SAME_SCENE:
            break
        i, j = pair
        groups[i] += groups.pop(j)
    for k, g in enumerate(groups):
        for i in g:
            vids[names[i]]["scene"] = k
    return len(groups)


def _smooth(x, n):
    if n <= 1 or len(x) < n:
        return x
    return np.convolve(x, np.ones(n) / n, mode="same")


def sample_masks(F):
    speed, roll, zoom, par, diff, bright, contrast, corr = F.T[:8]
    bad = (corr < 0.75) | (contrast < 10) | (bright < 20) | (bright > 235)
    if F.shape[1] > 8:
        bad |= _smooth(F[:, 8], SAMPLE_HZ) > OSD_TEXT
    still = _smooth(diff, SAMPLE_HZ // 2) < STILL_DIFF
    return bad, still


def interest(vids):
    """Adds v['I'] (interest per sample), v['bad'], v['still']; returns the normalisers."""
    pool = []
    for v in vids.values():
        v["bad"], v["still"] = sample_masks(v["feats"])
        ok = ~v["bad"] & ~v["still"]
        pool.append(v["feats"][ok, :4])
    pool = np.concatenate(pool) if pool else np.zeros((0, 4))
    norm = np.maximum(np.percentile(pool, 90, axis=0), 1e-6) if len(pool) > 50 else np.ones(4)
    for v in vids.values():
        n = np.minimum(v["feats"][:, :4] / norm, 3.0)
        raw = W["speed"] * n[:, 0] + W["roll"] * n[:, 1] + W["zoom"] * n[:, 2] + W["parallax"] * n[:, 3]
        raw[v["bad"] | v["still"]] = 0
        v["I"] = _smooth(raw, SAMPLE_HZ // 2)
    return dict(zip(W, norm.tolist()))


def parse_ranges(spec):
    """'hdz_030, hdz_031:12-40.5' -> {'hdz_030': [(0, inf)], 'hdz_031': [(12, 40.5)]}"""
    out = {}
    for part in filter(None, (p.strip() for p in (spec or "").split(","))):
        m = re.fullmatch(r"([^:]+?)(?::([\d.:]+)-([\d.:]+))?", part)
        if not m:
            raise SystemExit(f"can't read {part!r}: use VIDEO or VIDEO:START-END (seconds or m:ss)")
        name, a, b = m.groups()
        name = Path(name).stem
        rng = (to_s(a), to_s(b)) if a else (0.0, float("inf"))
        out.setdefault(name, []).append(rng)
    return out


def to_s(x):
    if x is None:
        return None
    parts = [float(p) for p in str(x).split(":")]
    s = 0.0
    for p in parts:
        s = s * 60 + p
    return s


def mmss(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


def _hist(img):
    h = cv2.calcHist([cv2.cvtColor(img, cv2.COLOR_BGR2HSV)], [0, 1, 2], None, [8, 4, 4], [0, 180, 0, 256, 0, 256])
    h = h.ravel()
    return h / (np.linalg.norm(h) + 1e-9)


def windows(v, name, clip, excl):
    """All candidate windows of one recording: (score, start_s, end_s, peak)."""
    dt, I = v["dt"], v["I"]
    L = max(2, int(round(clip / dt)))
    n = len(I)
    edge = int(round(EDGE_S / dt))
    if n < L + 2 * edge:
        return []
    bad = v["bad"].astype(float)
    stillrun = int(round(STILL_RUN_S / dt))
    st = v["still"].astype(np.int32)
    # longest still run inside each window, via a running count
    run = np.zeros(n, np.int32)
    for i in range(n):
        run[i] = run[i - 1] + 1 if (st[i] and i) else st[i]
    cs_I = np.concatenate([[0], np.cumsum(I)])
    cs_b = np.concatenate([[0], np.cumsum(bad)])
    out = []
    hop = max(1, int(round(0.5 / dt)))
    for s in range(edge, n - edge - L + 1, hop):
        e = s + L
        if run[s:e].max() > stillrun or (cs_b[e] - cs_b[s]) > 0.05 * L:
            continue
        t0, t1 = s * dt, e * dt
        if any(a < t1 and t0 < b for a, b in excl.get(name, [])):
            continue
        mean = (cs_I[e] - cs_I[s]) / L
        peak = float(I[s:e].max())
        out.append((mean + 0.25 * peak, t0, t1, peak))
    return out


def grow(v, start, end, clip, budget, excl, name):
    """Extend a chosen clip by 0.5 s steps while the action carries on (up to 1.6 x clip)."""
    dt, I = v["dt"], v["I"]
    n = len(I)
    s, e = int(round(start / dt)), int(round(end / dt))
    core = I[s:e].mean() if e > s else 0
    step = max(1, int(round(0.5 / dt)))
    edge = int(round(EDGE_S / dt))
    maxlen = int(round(1.6 * clip / dt))
    blocked = lambda a, b: any(x < b * dt and a * dt < y for x, y in excl.get(name, []))
    while (e - s) < maxlen and (e - s + step) * dt <= budget:
        cands = []
        if s - step >= edge and not blocked(s - step, s):
            cands.append(("s", I[s - step:s].mean(), v["still"][s - step:s].any()))
        if e + step <= n - edge and not blocked(e, e + step):
            cands.append(("e", I[e:e + step].mean(), v["still"][e:e + step].any()))
        cands = [c for c in cands if c[1] >= 0.6 * core and not c[2]]
        if not cands:
            break
        side = max(cands, key=lambda c: c[1])[0]
        if side == "s":
            s -= step
        else:
            e += step
    return s * dt, e * dt


def select(vids, length=60, clip=5, per_video=2, exclude=None, include=None, order="hook", per_scene=2):
    excl = parse_ranges(exclude)
    for name, rngs in excl.items():
        if name not in vids:
            print(f"  warning: --exclude {name}: no such usable recording")
    picked = []
    for name, rngs in parse_ranges(include).items():
        if name not in vids:
            raise SystemExit(f"--include {name}: no such usable recording")
        v = vids[name]
        for a, b in rngs:
            b = min(b, len(v["I"]) * v["dt"])
            s, e = int(a / v["dt"]), max(int(a / v["dt"]) + 1, int(b / v["dt"]))
            picked.append(dict(video=name, start=round(a, 2), end=round(b, 2), score=float(v["I"][s:e].mean()),
                               forced=True))
    budget = length - sum(p["end"] - p["start"] for p in picked)
    cands = []
    for name, v in vids.items():
        if any(a <= 0 and b == float("inf") for a, b in excl.get(name, [])):
            continue
        cands += [(sc, name, a, b, pk) for sc, a, b, pk in windows(v, name, clip, excl)]
    cands.sort(reverse=True)
    hists = [_hist(thumb_at(vids[p["video"]], (p["start"] + p["end"]) / 2)) for p in picked]
    per, per_sc = {}, {}
    for p in picked:
        per[p["video"]] = per.get(p["video"], 0) + 1
        sc_ = vids[p["video"]].get("scene", 0)
        per_sc[sc_] = per_sc.get(sc_, 0) + 1
    shortlist = []
    cap = per_scene
    while budget >= min(3.0, clip):
        before = len(picked)
        for sc, name, a, b, pk in cands:
            if budget < min(3.0, clip):
                break
            scene = vids[name].get("scene", 0)
            if per.get(name, 0) >= per_video or per_sc.get(scene, 0) >= cap:
                continue
            if any(p["video"] == name and a < p["end"] + MIN_GAP_S and p["start"] < b + MIN_GAP_S for p in picked):
                continue
            h = _hist(thumb_at(vids[name], (a + b) / 2))
            if any(float(h @ g) > SAME_VIEW for g in hists):
                continue
            if b - a > budget:
                b = a + budget
            a, b = grow(vids[name], a, b, clip, budget, excl, name)
            picked.append(dict(video=name, start=round(a, 2), end=round(b, 2), score=round(float(sc), 3),
                               forced=False, scene=scene))
            hists.append(h)
            per[name] = per.get(name, 0) + 1
            per_sc[scene] = per_sc.get(scene, 0) + 1
            budget -= b - a
        if len(picked) == before and cap >= len(picked) + 1:
            break                      # nothing more to take, even with no scene cap
        cap += 1
    for sc, name, a, b, pk in cands:
        if len(shortlist) >= 40:
            break
        if any(s["video"] == name and abs(s["start"] - a) < 4 for s in shortlist):
            continue
        sel = any(p["video"] == name and a < p["end"] and p["start"] < b for p in picked)
        shortlist.append(dict(video=name, start=round(a, 2), end=round(b, 2), score=round(float(sc), 3), picked=sel))
    if order == "time":
        picked.sort(key=lambda p: (p["video"], p["start"]))
    elif order == "hook" and picked:
        best = max(picked, key=lambda p: p["score"])
        rest = sorted((p for p in picked if p is not best), key=lambda p: (p["video"], p["start"]))
        picked = [best] + rest
    else:
        picked.sort(key=lambda p: -p["score"])
    return picked, shortlist


def thumb_at(v, t):
    th = v["thumbs"]
    return th[min(len(th) - 1, max(0, int(t)))]


def pick(work, good, videos_dir, length=60, clip=5, per_video=2, exclude=None, include=None, order="hook",
         per_scene=2):
    work = Path(work)
    vids = load(work, good)
    if not vids:
        raise SystemExit("No usable recordings")
    norm = interest(vids)
    n_scenes = scenes(vids)
    picked, shortlist = select(vids, length, clip, per_video, exclude, include, order, per_scene)
    if not picked:
        raise SystemExit("Nothing to pick: no moving, clear footage found (all parked, menus or static?)")
    for p in picked + shortlist:
        p["path"] = vids[p["video"]]["path"]
        p["fps"] = vids[p["video"]]["fps"]
    total_src = sum(len(v["I"]) * v["dt"] for v in vids.values())
    flying = sum(float((~v["still"] & ~v["bad"]).sum()) * v["dt"] for v in vids.values())
    res = dict(videos_dir=str(Path(videos_dir).resolve()), length=length, clip=clip, per_video=per_video,
               exclude=exclude, include=include, order=order, normalisers=norm,
               per_scene=per_scene, scenes=n_scenes, recordings=len(vids), footage_s=round(total_src, 1), moving_s=round(flying, 1),
               total_s=round(sum(p["end"] - p["start"] for p in picked), 2), clips=picked, candidates=shortlist)
    old = work / "picks.json"
    if old.exists():
        prev = json.loads(old.read_text())
        res["uploads"] = prev.get("uploads", [])
    old.write_text(json.dumps(res, indent=1))
    from .sheet import write_sheets
    sheets = write_sheets(work, vids, res)
    write_md(work, res, sheets)
    print(f"  {len(picked)} clips, {res['total_s']:.1f} s from {res['recordings']} recordings in {n_scenes} scenes "
          f"({total_src / 60:.0f} min, {flying / 60:.0f} min moving)")
    for i, p in enumerate(picked, 1):
        print(f"   {i:2d}. {p['video']:<14} {mmss(p['start'])}-{mmss(p['end'])}  {p['end'] - p['start']:.1f} s  "
              f"score {p['score']:.2f}  scene {vids[p['video']]['scene']}{'  (forced)' if p['forced'] else ''}")
    print(f"  review {work / 'picks.md'} and {sheets[0]}")
    return res


def write_md(work, res, sheets):
    L = [f"# Highlights: {Path(res['videos_dir']).name}", "",
         f"{len(res['clips'])} clips, **{res['total_s']:.1f} s** (max {res['length']:.0f} s), from "
         f"{res['recordings']} recordings ({res['footage_s'] / 60:.0f} min, {res['moving_s'] / 60:.0f} min moving).", "",
         "Check `" + Path(sheets[0]).name + "` (one row per clip, in the order of the short): every row must be "
         "real flight. Being carried, simulator/HDMI-in footage, menus or a crash ending don't belong. "
         "Leave out with `--exclude VIDEO` or `--exclude VIDEO:A-B`, force a moment in with "
         "`--include VIDEO:A-B` (seconds or m:ss in the recording), then re-run `pick` (seconds).", "",
         "| # | Recording | From | To | Length | Score |", "|---|---|---|---|---|---|"]
    for i, p in enumerate(res["clips"], 1):
        L.append(f"| {i} | {p['video']} | {mmss(p['start'])} | {mmss(p['end'])} | {p['end'] - p['start']:.1f} s | "
                 f"{p['score']:.2f}{' (forced)' if p['forced'] else ''} |")
    L += ["", f"## Other candidates (`{Path(sheets[1]).name}`)", "",
          "| Recording | From | To | Score | In the short |", "|---|---|---|---|---|"]
    for c in res["candidates"]:
        L.append(f"| {c['video']} | {mmss(c['start'])} | {mmss(c['end'])} | {c['score']:.2f} | "
                 f"{'yes' if c['picked'] else ''} |")
    (Path(work) / "picks.md").write_text("\n".join(L) + "\n")
