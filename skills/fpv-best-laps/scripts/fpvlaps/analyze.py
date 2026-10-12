"""Pass 2 — arm segments (OSD), track calibration, lap detection, crash filtering, best 3 consecutive laps."""
import json
from pathlib import Path
import numpy as np
from . import osd
from . import track as track_mod
from .config import (OCR_STEP, DTW_CANDIDATE_COST, CLEAN_COST_MIN, CLEAN_COST_MAX, CLEAN_COST_PCTL,
                     CLEAN_COST_FACTOR, FAST_OUTLIER, GATE_FIT_MIN, LAP_MIN_FACTOR,
                     LAP_MAX_FACTOR, STALL_MOTION, STALL_SECS, FLIGHT_MOTION, LAPS_PER_RESULT, DTW_STEP,
                     SHORT_LOOP_RATIO, MAX_REFERENCE_TRIES, CHAIN_MIN)
from .extract import load
from .laps import fine_desc, dtw_desc, lap_matches, refine, stalled, window
from .report import write_reports


def flight_segments_from_motion(motion, fps):
    """Fallback when no OSD timer is readable: flying = sustained motion; gaps < 1.5 s are bridged."""
    m = np.convolve(motion, np.ones(int(fps)) / int(fps), "same") > FLIGHT_MOTION * 0.6
    segs, start = [], None
    for i, f in enumerate(m):
        if f and start is None:
            start = i
        if not f and start is not None:
            segs.append([start, i - 1])
            start = None
    if start is not None:
        segs.append([start, len(m) - 1])
    out = []
    for s in segs:
        if out and s[0] - out[-1][1] < 1.5 * fps:
            out[-1][1] = s[1]
        else:
            out.append(s)
    return [(int(s[0]), int(s[1])) for s in out if s[1] - s[0] > 3 * fps]


def arm_info(v):
    """Armed segments from the OSD timer. Any timer that only counts while armed works on its own
    (per-arm, or total armed time). With several timers, the one that reveals the most disarms wins
    (a per-arm timer also resets on a quick re-arm; a power-on timer never stops), ties going to the
    smaller reading."""
    if v["cells"] is None:
        return flight_segments_from_motion(v["motion"], v["fps"]), "motion (no OSD timer found)"
    secs = osd.to_seconds(osd.classify(v["cells"]))               # (samples, timers)
    readable = np.mean(~np.isnan(secs), 0)
    rows = [r for r in range(secs.shape[1]) if readable[r] > 0.3]
    if not rows:
        return flight_segments_from_motion(v["motion"], v["fps"]), "motion (OSD unreadable)"
    segs = {r: osd.arm_segments(secs[:, r], v["fps"], OCR_STEP) for r in rows}
    row = min(rows, key=lambda r: (-len(segs[r]), np.nanmedian(secs[:, r])))
    if not segs[row]:
        return flight_segments_from_motion(v["motion"], v["fps"]), "motion (OSD timer never ran)"
    return segs[row], f"OSD timer {row + 1} of {secs.shape[1]}"


def load_all(work, names, log):
    vids = []
    for n in names:
        v = load(work, n)
        v["F"] = fine_desc(v["thumbs"])
        v["X"] = dtw_desc(v["thumbs"])
        v["segments"], v["arm_source"] = arm_info(v)
        log(f"  {n}: {v['n'] / v['fps']:.0f}s, armed via {v['arm_source']}: "
            + ", ".join(f"{a / v['fps']:.0f}-{b / v['fps']:.0f}s" for a, b in v["segments"]))
        vids.append(v)
    return vids


def save_profile(work, ref, T, wins):
    p = Path(work) / "track.json"
    p.write_text(json.dumps(ref, indent=1))
    np.savez_compressed(Path(work) / "track.npz", T=T, wins=np.array(wins))
    return p


def load_profile(path):
    p = Path(path)
    ref = json.loads(p.read_text())
    z = np.load(p.with_suffix(".npz"))
    return ref, z["T"], list(z["wins"])


def find_laps(v, matches, wins):
    """Lap boundaries (DTW steps) -> exact crossing frames, refined against crossing templates `wins`."""
    fps = v["fps"]
    cache = {}

    def cross(i):
        if i not in cache:
            cache[i] = refine(v["F"], i * DTW_STEP, wins)
        return cache[i]

    laps = []
    for s, e, cost in matches:
        (a, fa), (b, fb) = cross(s), cross(e)
        if b > a:
            laps.append(dict(video=v["name"], start=int(a), end=int(b), cost=round(cost, 4), fit=[round(fa, 3), round(fb, 3)]))
    laps.sort(key=lambda l: l["start"])
    for p, q in zip(laps, laps[1:]):                     # adjacent laps share one crossing
        if abs(q["start"] - p["end"]) <= 30:
            q["start"] = p["end"]
    for l in laps:
        l["time"] = round((l["end"] - l["start"]) / fps, 3)
    return laps


def consensus_template(vids, laps_by_video, max_n=40):
    """Mean +-0.5 s window over the crossings of the best-matching laps in all videos. Averaging many
    real gate passes keeps what they share and washes out one lap's line or speed."""
    cand = []
    for v in vids:
        for l in laps_by_video[v["name"]]:
            for c in (l["start"], l["end"]):
                w = window(v["F"], c)
                if w is not None:
                    cand.append((l["cost"], w))
    cand.sort(key=lambda t: t[0])
    if len(cand) < 6:
        return None
    W = np.mean([w for _, w in cand[:max_n]], 0)
    W -= W.mean(1, keepdims=True)
    W /= W.std(1, keepdims=True) + 1e-6
    return W


def classify(v, laps, P, clean_thr):
    fps = v["fps"]

    def seg_of(f):
        return next((i for i, (a, b) in enumerate(v["segments"]) if a <= f <= b), None)

    for l in laps:
        why = []
        if l["cost"] > clean_thr:
            why.append(f"off-line/crash: lap doesn't match the reference lap (cost {l['cost']:.2f} > {clean_thr:.2f})")
        if min(l["fit"]) < GATE_FIT_MIN:
            which = "start" if l["fit"][0] < l["fit"][1] else "end"
            why.append(f"lap {which} doesn't look like a gate pass (fit {min(l['fit']):.2f}): missed / re-flown gate")
        sa, sb = seg_of(l["start"]), seg_of(l["end"])
        if sa is None or sa != sb:
            why.append("disarmed during lap (OSD timer stopped/reset)")
        if not (LAP_MIN_FACTOR * P <= l["time"] <= LAP_MAX_FACTOR * P):
            why.append(f"implausible duration {l['time']:.2f}s")
        if stalled(v["motion"], l["start"], l["end"], STALL_MOTION, STALL_SECS, fps):
            why.append("quad stopped inside the lap (crash)")
        l["clean"] = not why
        l["reason"] = "; ".join(why)


def best_windows(all_laps, n=LAPS_PER_RESULT, top=5):
    """Sliding window of n consecutive clean laps (each lap starts where the previous ended)."""
    res = []
    by_video = {}
    for l in all_laps:
        by_video.setdefault(l["video"], []).append(l)
    for name, L in by_video.items():
        L.sort(key=lambda l: l["start"])
        for i in range(len(L) - n + 1):
            w = L[i:i + n]
            if all(l["clean"] for l in w) and all(w[k]["end"] == w[k + 1]["start"] for k in range(n - 1)):
                res.append(dict(video=name, laps=w, total=round(sum(l["time"] for l in w), 3),
                                start=w[0]["start"], end=w[-1]["end"]))
    res.sort(key=lambda r: r["total"])
    return res[:top]


def chain_ratio(vids, laps_by_video, P):
    """Share of back-to-back laps (same armed segment, less than half a lap apart) that share their
    crossing. With a reference that starts and ends at the start gate, consecutive laps chain; with
    one that doesn't, every lap ends a few seconds before the next one starts."""
    chained = gapped = 0
    for v in vids:
        L = laps_by_video[v["name"]]
        for p, q in zip(L, L[1:]):
            if (q["start"] - p["end"]) / v["fps"] > 0.5 * P:
                continue                                   # landed / crashed in between
            if not any(a <= p["end"] and q["start"] <= b for a, b in v["segments"]):
                continue
            if q["start"] == p["end"]:
                chained += 1
            else:
                gapped += 1
    return chained / (chained + gapped) if chained + gapped else 1.0


def detect(vids, T, wins, P):
    """Laps of every video against reference lap T: (all laps classified, clean threshold, typical lap,
    chain ratio)."""
    matches = {v["name"]: lap_matches(v["X"], T, DTW_CANDIDATE_COST) for v in vids}
    raw = {v["name"]: find_laps(v, matches[v["name"]], wins) for v in vids}         # pass 1: reference crossings
    cons = consensus_template(vids, raw)
    if cons is not None:                                                            # pass 2: consensus crossing
        raw = {v["name"]: find_laps(v, matches[v["name"]], [cons]) for v in vids}
    chain = chain_ratio(vids, raw, P)
    costs = np.array([l["cost"] for L in raw.values() for l in L])
    # anchored on the well-matching laps, so lots of junk candidates can't loosen it
    base = float(np.percentile(costs, CLEAN_COST_PCTL)) if len(costs) else 0.2
    clean_thr = float(np.clip(base * CLEAN_COST_FACTOR, CLEAN_COST_MIN, CLEAN_COST_MAX))
    all_laps = []
    for v in vids:
        classify(v, raw[v["name"]], P, clean_thr)
        all_laps += raw[v["name"]]
    typical = float(np.median([l["time"] for l in all_laps if l["clean"]] or [P]))
    for l in all_laps:                         # a lap far faster than the pilot's norm skipped part of the track
        if l["time"] < FAST_OUTLIER * typical:
            l["clean"] = False
            l["reason"] = "; ".join(r for r in (l["reason"], f"{l['time']:.2f}s is implausibly fast for this "
                                    f"track (typical {typical:.2f}s): missed gate / cut course") if r)
    return all_laps, clean_thr, typical, chain


def reference_problems(typical, chain, P):
    """Why the laps suggest a wrong reference lap ([] = looks right)."""
    out = []
    if typical < SHORT_LOOP_RATIO * P:
        out.append(f"the typical clean lap ({typical:.2f}s) is only {typical / P:.0%} of the track's lap "
                   f"period ({P:.2f}s), so the reference probably skips part of the course (e.g. a dive)")
    if chain < CHAIN_MIN:
        out.append(f"only {chain:.0%} of back-to-back laps share their crossing, so the reference probably "
                   f"doesn't start and end at the start gate")
    return out


def reference_warning(ref, problems):
    return (f"The reference lap ({ref['video']} {ref['start']}->{ref['end']}) looks wrong: "
            + "; ".join(problems) + ". Laps timed against it can't be trusted. Re-run with --anchor on a "
            "start-gate crossing that begins a full, correct lap.")


def analyze(work, names, track=None, anchor=None, videos_dir=None, log=print):
    vids = load_all(work, names, log)
    fps = vids[0]["fps"]
    warnings = []
    if track:
        ref, T, wins = load_profile(track)
        log(f"  using track profile {track} (reference {ref['video']} {ref['start']}->{ref['end']})")
        # lap length checks use this session's own period: the pilot may be much faster than when the
        # profile was made
        P = track_mod.lap_period(vids) or ref["period_s"]
        log(f"  lap period this session ~{P:.2f}s (profile: {ref['period_s']:.2f}s)")
        all_laps, clean_thr, typical, chain = detect(vids, T, wins, P)
    elif anchor:
        name, frame = anchor.rsplit(":", 1)
        ref = track_mod.reference_from_anchor(vids, Path(name).stem, int(frame), log)
        T, wins = track_mod.reference_arrays(vids, ref)
        P = ref["period_s"]
        all_laps, clean_thr, typical, chain = detect(vids, T, wins, P)
    else:
        P, cands = track_mod.reference_candidates(vids, log)
        tried = []
        for k, (ref0, rv) in enumerate(cands[:MAX_REFERENCE_TRIES]):
            ref = track_mod.finalize_reference(vids, ref0, rv, P, log)
            T, wins = track_mod.reference_arrays(vids, ref)
            out = detect(vids, T, wins, P)
            tried.append((ref, T, wins, out))
            log(f"  reference {ref['video']} {ref['start']}->{ref['end']}: typical clean lap {out[2]:.2f}s "
                f"({out[2] / P:.0%} of the lap period), {out[3]:.0%} of back-to-back laps chained")
            problems = reference_problems(out[2], out[3], P)
            if not problems:
                break
            log(f"  -> rejected: {'; '.join(problems)}; trying the next candidate")
        ref, T, wins, (all_laps, clean_thr, typical, chain) = max(
            tried, key=lambda t: min(t[3][2] / P, 1.0) + min(t[3][3], CHAIN_MIN))
    problems = reference_problems(typical, chain, P)
    if problems:
        warnings.append(reference_warning(ref, problems))
    if not track:
        rv = next(v for v in vids if v["name"] == ref["video"])
        ref["path"], ref["pic_box"], ref["fps"] = rv["video"], rv["pic_box"], rv["fps"]
        save_profile(work, ref, T, wins)

    windows = best_windows(all_laps)
    for w in windows:                          # flag windows that need a human/agent look before trusting
        w["warnings"] = [f"lap {i + 1} ({l['time']:.2f}s) is >10% faster than the typical {typical:.2f}s lap: "
                         f"check the crossings sheet (missed gate / re-flown gate?)"
                         for i, l in enumerate(w["laps"]) if l["time"] < 0.9 * typical]
    result = dict(videos_dir=str(Path(videos_dir).resolve()) if videos_dir else None,
                  fps=fps, laps_per_result=LAPS_PER_RESULT, lap_period_s=P, clean_cost_threshold=clean_thr,
                  typical_lap_s=typical, chain_ratio=chain, warnings=warnings,
                  reference=ref, videos=[dict(name=v["name"], path=v["video"], seconds=v["n"] / v["fps"],
                                               armed_segments=v["segments"], arm_source=v["arm_source"])
                                          for v in vids],
                  laps=all_laps, best=windows)
    (Path(work) / "result.json").write_text(json.dumps(result, indent=1))
    write_reports(work, result, log)
    return result
