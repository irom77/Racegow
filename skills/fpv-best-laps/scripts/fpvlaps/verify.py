"""Verify a claimed result (e.g. a leaderboard submission) against the laps found in the footage.

Reads <work>/result.json (from `analyze`) and writes verify.md + verify.json with a verdict:

  verified         a chain of 3 clean consecutive laps matches the claim within the tolerance
  mismatch         no clean chain matches (the closest ones are listed, with timestamps to review)
  not verifiable   no 3-lap chain at all, or the reference lap looks wrong, so nothing can be timed
  detected         no claim given: the best clean chain is reported

Edits in an uploaded video are found from the OSD timer: a timer that counts while armed (or since
power-on) advances exactly as fast as the footage, so "timer minus video time" is constant until the
footage is cut. Laps that span such a jump are rejected."""
import json
import re
from pathlib import Path
import numpy as np
from . import osd
from .config import LAPS_PER_RESULT, OCR_STEP, GATE_FIT_MIN
from .extract import load
from .report import crossing_sheet

CROSSING_FRAMES = 3          # crossing accuracy: +-3 frames (+-0.05 s at 60 fps)
SPLIT_TOL = 0.15             # s; claimed lap times, for information only: pilots time from their own line
                             # (gate, start pad, a lap timer), which shifts single laps but hardly the total
TIMER_TOL = 0.15             # s; OSD refresh jitter allowed when fitting the timer to video time
MIN_COVER = 0.5              # share of a video the timer must be read consistently over to check it for edits
UPLOAD_COST_SPREAD = 1.25    # a lap within this x the upload's median match cost isn't singled out as off-line
MIN_RUN_S = 1.5              # timer runs shorter than this are OCR glitches or a frozen (disarmed) timer
                             # (a frozen reading fits one offset for up to 1 s + TIMER_TOL)


def parse_claim(s):
    """'30.82' -> total only; '10.27,10.33,10.22' (or '10.27+10.33+10.22') -> 3 laps + their total."""
    if not s:
        return None
    parts = [p for p in re.split(r"[,+;\s]+", s.strip().rstrip("s")) if p]
    try:
        vals = [float(p.rstrip("s")) for p in parts]
    except ValueError:
        raise SystemExit(f"--claim {s!r}: expected a total (30.82) or {LAPS_PER_RESULT} lap times (10.27,10.33,10.22)")
    if len(vals) == 1:
        return dict(total=vals[0], laps=None)
    if len(vals) != LAPS_PER_RESULT:
        raise SystemExit(f"--claim {s!r}: give the total or exactly {LAPS_PER_RESULT} lap times")
    return dict(total=round(sum(vals), 3), laps=vals)


def tolerance(fps, override=None):
    """Per-lap tolerance: +-3 frames, i.e. 0.05 s at 60 fps, 0.10 s at 30 fps (never below 0.05 s)."""
    return float(override) if override is not None else max(0.05, CROSSING_FRAMES / fps)


# ---- edits (cuts) from the OSD timer --------------------------------------------------------------

def agreed(secs, fps, step=OCR_STEP, tol=TIMER_TOL, half_window_s=1.0):
    """Readings that at least half of the readings within +-1 s agree with (same clock offset within
    1 s + tol). Frequent OCR misreads (1 in 4 digits on some uploads) would otherwise split every run
    into pieces too short to keep; on either side of a real edit, the readings still agree with
    their own side."""
    t = np.arange(len(secs)) * step / fps
    k = np.where(~np.isnan(secs))[0]
    off = secs[k] - t[k]
    tk = t[k]
    out = secs.copy()
    for n, i in enumerate(k):
        lo, hi = np.searchsorted(tk, tk[n] - half_window_s), np.searchsorted(tk, tk[n] + half_window_s, "right")
        if np.mean(np.abs(off[lo:hi] - off[n]) < 1 + tol) < 0.5:
            out[i] = np.nan
    return out


def timer_runs(secs, fps, step=OCR_STEP, tol=TIMER_TOL, min_len_s=MIN_RUN_S):
    """Stretches where an mm:ss timer reading fits `floor(video time + c)` with one constant c.
    Each reading s at time t bounds c to [s - t, s - t + 1); a run keeps the intersection, so after a
    few ticks c is known to a frame or two. Returns [dict(a, b, c, first)] (sample indices, offset,
    timer reading at the start), OCR glitches and frozen-timer stretches dropped."""
    secs = agreed(secs, fps, step, tol)
    t = np.arange(len(secs)) * step / fps
    runs, cur = [], None
    for k in np.where(~np.isnan(secs))[0]:
        lo, hi = secs[k] - t[k], secs[k] - t[k] + 1
        if cur and lo < cur["hi"] + tol and hi > cur["lo"] - tol and t[k] - t[cur["b"]] < 2.0:
            cur["b"], cur["last"] = k, float(secs[k])
            if max(cur["lo"], lo) <= min(cur["hi"], hi):  # a reading only inside the jitter allowance
                cur["lo"], cur["hi"] = max(cur["lo"], lo), min(cur["hi"], hi)   # must not move c
        else:
            cur = dict(a=k, b=k, lo=lo, hi=hi, first=float(secs[k]), last=float(secs[k]))
            runs.append(cur)
    runs = [r for r in runs if t[r["b"]] - t[r["a"]] >= min_len_s and r["last"] > r["first"]]
    merged = []                                           # rejoin runs split only by a glitch
    for r in runs:
        p = merged[-1] if merged else None
        if p and r["lo"] < p["hi"] + tol and r["hi"] > p["lo"] - tol and t[r["a"]] - t[p["b"]] < 2.0:
            p["b"] = r["b"]
            if max(p["lo"], r["lo"]) <= min(p["hi"], r["hi"]):
                p["lo"], p["hi"] = max(p["lo"], r["lo"]), min(p["hi"], r["hi"])
        else:
            merged.append(dict(r))
    for r in merged:
        r["c"] = (r["lo"] + r["hi"]) / 2
    return merged


def timer_jumps(secs, fps, step=OCR_STEP):
    """Discontinuities between consecutive timer runs: [dict(frame, kind, shift, before, after)].
    kind: 'cut' (footage removed or replayed), 're-arm' (timer reset to ~0) or 'pause' (timer frozen
    while disarmed, then resumed)."""
    runs = timer_runs(secs, fps, step)
    out = []
    for p, q in zip(runs, runs[1:]):
        shift = q["c"] - p["c"]
        gap = (q["a"] - p["b"]) * step / fps
        before = float(secs[p["b"]])
        if abs(shift) <= 2 * TIMER_TOL and q["first"] >= before:
            continue                              # same offset: the timer was only unreadable for a while
        if q["first"] <= 2 and q["first"] < before:
            kind = "re-arm"
        elif shift > 2 * TIMER_TOL or (shift < -2 * TIMER_TOL and gap < 0.5):
            kind = "cut"                          # the timer jumped ahead of (or back behind) the footage
        else:
            kind = "pause"
        out.append(dict(frame=int(q["a"] * step), kind=kind, shift=round(shift, 2), before=before,
                        after=q["first"]))
    return out


def shift_at(runs, frame, fps, step=OCR_STEP, within=3.0):
    """Offset change across `frame` in one timer's runs, or None when the timer wasn't read on both
    sides within `within` seconds."""
    if any(r["a"] * step < frame <= r["b"] * step for r in runs):
        return 0.0                                # one unbroken run straddles it
    before = [r for r in runs if r["b"] * step < frame and (frame - r["b"] * step) / fps <= within]
    after = [r for r in runs if r["a"] * step >= frame and (r["a"] * step - frame) / fps <= within]
    return after[0]["c"] - before[-1]["c"] if before and after else None


def confirmed_cuts(secs, rows, fps, step=OCR_STEP):
    """Jumps of the first (most readable) timer row; a cut must show the same shift on every other
    timer read around it. Footage cuts move all timers alike; a mode switch that puts a different
    timer in the same OSD slot (e.g. Betaflight's crash-flip / turtle mode) moves only one."""
    jumps = timer_jumps(secs[:, rows[0]], fps, step)
    others = [timer_runs(secs[:, r], fps, step) for r in rows[1:]]
    out = []
    for j in jumps:
        if j["kind"] == "cut":
            seen = [shift_at(runs, j["frame"], fps, step) for runs in others]
            if any(d is not None and abs(d - j["shift"]) > 2 * TIMER_TOL for d in seen):
                continue                          # another timer disagrees: an OSD artefact, not an edit
        out.append(j)
    return out


def osd_edits(work, name):
    """(jumps, timer description, timer spans) for one analysed video: jumps of its most readable OSD
    timer, cuts cross-checked against the other timers; spans = [(first, last frame)] of its runs."""
    v = load(work, name)
    if v["cells"] is None:
        return None, "no OSD timer found", []
    secs = osd.to_seconds(osd.classify(v["cells"]))
    readable = np.mean(~np.isnan(secs), 0)
    rows = [int(r) for r in np.argsort(-readable) if readable[r] >= 0.3]
    if not rows:
        return None, "OSD timer unreadable", []
    how = f"OSD timer {rows[0] + 1} of {secs.shape[1]} ({readable[rows[0]]:.0%} readable)"
    if len(rows) > 1:
        how += ", cross-checked with " + ", ".join(f"timer {r + 1}" for r in rows[1:])
    spans = [(int(r["a"] * OCR_STEP), int(r["b"] * OCR_STEP)) for r in timer_runs(secs[:, rows[0]], v["fps"])]
    cover = sum(b - a for a, b in spans) / max(1, v["n"])
    how += f"; a running clock fits {cover:.0%} of the video"
    if cover < MIN_COVER:
        return None, how + ", too little to check for edits", spans
    return confirmed_cuts(secs, rows, v["fps"]), how, spans


# ---- matching the claim ---------------------------------------------------------------------------

def chains(laps, n=LAPS_PER_RESULT):
    """Every run of n consecutive laps in one video that share their crossings, clean or not."""
    by_video, out = {}, []
    for l in laps:
        by_video.setdefault(l["video"], []).append(l)
    for name, L in by_video.items():
        L = sorted(L, key=lambda l: l["start"])
        for i in range(len(L) - n + 1):
            w = L[i:i + n]
            if all(w[k]["end"] == w[k + 1]["start"] for k in range(n - 1)):
                out.append(dict(video=name, laps=w, total=round(sum(l["time"] for l in w), 3),
                                start=w[0]["start"], end=w[-1]["end"]))
    return out


def cost_levels(R):
    """Median match cost of each video's laps. Re-encoding and burned-in overlays raise every lap's
    cost in an upload alike, so a lap is only off-line if it stands out from its own video."""
    by = {}
    for l in R["laps"]:
        by.setdefault(l["video"], []).append(l["cost"])
    return {n: float(np.median(c)) for n, c in by.items()}


DISARM = "disarmed during lap"


def timer_unbroken(l, timer, fps, near_s=1.5):
    """The OSD timer was read close to both ends of the lap and has no discontinuity (re-arm, pause,
    edit) inside it: the quad stayed armed, whatever the motion-based arm detection guessed."""
    if not timer or timer.get("jumps") is None:
        return False
    if any(l["start"] < j["frame"] <= l["end"] for j in timer["jumps"]):
        return False
    near = near_s * fps

    def seen(f):
        return any(a - near <= f <= b + near for a, b in timer["spans"])
    return seen(l["start"]) and seen(l["end"])


def offline_only(l, level, clean_thr, reasons=None):
    """True when the lap was rejected only for its match cost, the whole video's cost level is above
    the clean limit, this lap is in line with it, and both crossings still look like the gate pass."""
    if reasons is None:
        reasons = [r for r in l["reason"].split("; ") if r]
    return (bool(reasons) and all(r.startswith("off-line/crash") for r in reasons)
            and level > clean_thr and l["cost"] <= UPLOAD_COST_SPREAD * level and min(l["fit"]) >= GATE_FIT_MIN)


def problems(w, cuts, level=None, clean_thr=None, timer=None, fps=60.0):
    """(why a chain can't count, caveats): rejected laps and laps spanning an edit. Two rejections become
    caveats instead: a disarm guessed from motion that the OSD timer contradicts (`timer`: the video's
    OSD jumps and spans, only when arm detection fell back to motion), and a match cost raised across
    the whole upload."""
    out, soft = [], []
    for i, l in enumerate(w["laps"], 1):
        reasons = [r for r in l["reason"].split("; ") if r]
        if any(r.startswith(DISARM) for r in reasons) and timer_unbroken(l, timer, fps):
            reasons = [r for r in reasons if not r.startswith(DISARM)]
            soft.append(f"lap {i}: motion suggested a disarm, but the OSD timer runs unbroken through the lap")
        if not reasons:
            pass
        elif level is not None and offline_only(l, level, clean_thr, reasons):
            soft.append(f"lap {i} matches the reference less well than a clean lap (cost {l['cost']:.2f} > "
                        f"{clean_thr:.2f}), but so does this whole video (median {level:.2f}): typical of a "
                        f"re-encoded upload or a burned-in overlay")
        else:
            out.append(f"lap {i} rejected: {'; '.join(reasons)}")
        for c in cuts:
            if l["start"] < c["frame"] <= l["end"]:
                out.append(f"lap {i} spans an edit (OSD timer jumps {c['shift']:+.2f}s at frame {c['frame']})")
    return out, soft


def error(w, claim):
    """Difference to the claimed 3-lap total. Lap times aren't judged: a timing line a few frames
    further along the track moves time from one lap to the next, but not out of the total."""
    return abs(w["total"] - claim["total"])


def split_notes(w, claim):
    """Claimed lap times off by more than SPLIT_TOL (information, not part of the verdict)."""
    if not claim or not claim["laps"]:
        return []
    return [f"lap {i} is {l['time'] - c:+.2f}s off the claimed {c:.2f}s"
            for i, (l, c) in enumerate(zip(w["laps"], claim["laps"]), 1) if abs(l["time"] - c) > SPLIT_TOL]


def judge(R, claim, tol, cuts_by_video, timers=None):
    """(verdict, why, matched/closest chain or None, other close chains)."""
    cand = chains(R["laps"])
    levels = cost_levels(R)
    for w in cand:
        w["problems"], w["caveats"] = problems(w, cuts_by_video.get(w["video"]) or [], levels.get(w["video"]),
                                               R.get("clean_cost_threshold"), (timers or {}).get(w["video"]),
                                               R.get("fps", 60.0))
        w["error"] = round(error(w, claim), 3) if claim else None
    good = [w for w in cand if not w["problems"]]
    ref_bad = bool(R.get("warnings"))
    if not cand:
        return "not verifiable", f"no {LAPS_PER_RESULT} consecutive laps were found in the footage", None, []
    if not claim:
        if not good:
            return "not verifiable", f"no {LAPS_PER_RESULT} consecutive clean laps", None, []
        best = min(good, key=lambda w: w["total"])
        return "detected", "no claim given; best clean chain reported", best, []
    cand.sort(key=lambda w: (w["error"], bool(w["problems"])))
    match = next((w for w in cand if w["error"] <= tol and not w["problems"]), None)
    if ref_bad:
        return ("not verifiable", "the reference lap looks wrong, so lap times can't be trusted: "
                + " ".join(R["warnings"]), match or cand[0], cand[1:4])
    if match:
        why = f"the 3-lap total matches the claim within +-{tol:.2f}s"
        notes = split_notes(match, claim)
        if notes:
            why += ("; " + ", ".join(notes) + " (lap times differ more than a timing line moved a few frames "
                    "would explain: compare the laps in the crossing sheet)")
        elif claim["laps"]:
            why += f", and every claimed lap time within +-{SPLIT_TOL:.2f}s"
        if match["caveats"]:
            why += "; the whole video matches the reference lap less well than raw footage, so check the crossing sheet"
        return "verified", why, match, []
    near = cand[0]
    if near["error"] <= tol:
        return ("mismatch", "the claimed times are in the footage, but those laps don't count: "
                + "; ".join(near["problems"]), near, [w for w in cand[1:4] if not w["problems"]][:2])
    closest_good = min(good, key=lambda w: w["error"]) if good else None
    why = f"no chain of {LAPS_PER_RESULT} laps matches the claimed total within +-{tol:.2f}s"
    if closest_good:
        why += f" (closest clean chain: {closest_good['total']:.2f}s, off by {closest_good['error']:.2f}s)"
    return "mismatch", why, closest_good or near, [w for w in cand[:4] if w is not (closest_good or near)][:3]


# ---- output ---------------------------------------------------------------------------------------

def _clock(s):
    m, s = divmod(s, 60)
    h, m = divmod(int(m), 60)
    return (f"{h}:{m:02d}:" if h else f"{m}:") + f"{s:05.2f}"


def crossings(w, fps, src):
    """[(label, frame, source seconds, link or None)] for the 4 gate crossings of a chain."""
    off = (src or {}).get("offset_s") or 0.0
    frames = [w["laps"][0]["start"]] + [l["end"] for l in w["laps"]]
    out = []
    for i, f in enumerate(frames):
        t = off + f / fps
        lab = "start" if i == 0 else f"end of lap {i}"
        out.append((lab, f, t, link(src["id"], t) if src and src.get("id") else None))
    return out


def link(vid, t):
    from .youtube import link as yt_link
    return yt_link(vid, t)


def reference_certainty(R, src=None):
    tr = R.get("track_readme") or {}
    how = tr.get("reference") or ""
    if R.get("track_profile") or "track profile" in how:
        if src:
            return ("track profile from other footage. **Valid only if this video was flown on the same "
                    "build of the track** (same room): each pilot builds the layout at home, and a profile "
                    "from another room can still produce laps. For another pilot's video, re-run with "
                    "`--no-readme --anchor <id>:FRAME` on their start-gate pass"), True
        return "track profile (layout calibrated from other footage)", True
    if R["reference"].get("source") in ("anchor", "readme"):
        return f"start-gate crossing given by hand ({R['reference']['source']})", True
    if len(R["videos"]) == 1:
        return ("automatic calibration from this one video: **less certain**. The start gate and the "
                "racing line are learned from the same laps being checked; pass `--track` with a profile "
                "from other footage of the same build of the layout for a firmer verdict"), False
    return "automatic calibration", False


def write(work, R, claim, tol, verdict, why, w, others, src, edits, log=print):
    work = Path(work)
    fps = R["fps"]
    ref_text, firm = reference_certainty(R, src)
    lines = ["# Run verification", ""]
    if src:
        lines += [f"Video: [{src.get('title') or src['id']}]({src['url']})"
                  + (f" by {src['uploader']}" if src.get("uploader") else "")
                  + f", {src['fps']:g} fps"
                  + (f" (analysed at {src['analysis_fps']:g} fps)" if src.get("analysis_fps", src["fps"]) != src["fps"] else "")
                  + (f", section {_clock(src['offset_s'])}-{_clock(src['end_s']) if src.get('end_s') else 'end'}"
                     if src.get("offset_s") or src.get("end_s") else "")
                  + (" (variable frame rate, normalised)" if src.get("variable_frame_rate") else ""), ""]
    elif R.get("videos_dir"):
        lines += [f"Videos: `{R['videos_dir']}`", ""]
    lines += [f"## Verdict: **{verdict.upper()}**", "", why[0].upper() + why[1:] + ".", ""]
    if claim:
        lines.append(f"- Claim: {claim['total']:.2f}s"
                     + (" = " + " + ".join(f"{c:.2f}" for c in claim["laps"]) if claim["laps"] else ""))
        lines.append(f"- Tolerance: +-{tol:.2f}s on the 3-lap total at {(src or {}).get('fps') or fps:g} fps"
                     + (f"; lap times are shown against +-{SPLIT_TOL:.2f}s for information only (the pilot's "
                        "timing line can sit a few frames from the tool's)" if claim["laps"] else ""))
    lines.append(f"- Reference lap: {ref_text}")
    if not firm and verdict == "verified":
        lines.append("- Without a profile from other footage the verdict rests on the video agreeing with "
                     "itself; check the crossing sheet below against the track's demo flythrough.")
    lines.append("")
    if w:
        head = {"verified": "Matching laps", "detected": "Best clean laps"}.get(verdict, "Closest laps")
        lines += [f"## {head}: `{w['video']}` {w['total']:.2f}s", ""]
        cols = "| Lap | Detected |" + (" Claimed | Diff |" if claim and claim["laps"] else "") + " Status |"
        lines += [cols, "|" + "---|" * (cols.count("|") - 1)]
        for i, l in enumerate(w["laps"]):
            row = f"| {i + 1} | {l['time']:.2f}s |"
            if claim and claim["laps"]:
                d = l["time"] - claim["laps"][i]
                row += f" {claim['laps'][i]:.2f}s | {d:+.2f}s{' ⚠' if abs(d) > SPLIT_TOL else ''} |"
            if l["clean"]:
                row += " clean |"
            elif any(p.startswith(f"lap {i + 1} rejected") for p in w["problems"]):
                row += f" rejected: {l['reason']} |"
            else:
                row += " counted, see caveats |"
            lines.append(row)
        tot = f"| **Total** | **{w['total']:.2f}s** |"
        if claim and claim["laps"]:
            d = w["total"] - claim["total"]
            tot += f" {claim['total']:.2f}s | {d:+.2f}s{' ⚠' if abs(d) > tol else ''} | |"
        elif claim:
            d = w["total"] - claim["total"]
            tot += f" claimed {claim['total']:.2f}s, {d:+.2f}s{' ⚠' if abs(d) > tol else ''} |"
        else:
            tot += " |"
        lines += [tot, ""]
        if w.get("caveats"):
            lines += ["**Caveats:**", ""] + [f"- {c}" for c in w["caveats"]] + [""]
        if w.get("problems"):
            lines += ["**Why these laps don't count:**", ""] + [f"- {p}" for p in w["problems"]] + [""]
        lines += ["### Gate crossings to review", "", "| Crossing | Frame | Video time | Link |", "|---|---|---|---|"]
        for lab, f, t, u in crossings(w, fps, src):
            lines.append(f"| {lab} | {f} | {_clock(t)} | {f'[open]({u})' if u else '-'} |")
        lines += ["", "Crossing sheet (each row one crossing, all rows should show the same spot at the start "
                  "gate): ![crossings](sheets/verify_crossings.jpg)", ""]
    if others:
        lines += ["## Other close chains", "", "| Video | Total | Laps | Starts at | Notes |", "|---|---|---|---|---|"]
        off = (src or {}).get("offset_s") or 0.0
        for o in others:
            t = off + o["start"] / fps
            at = f"[{_clock(t)}]({link(src['id'], t)})" if src and src.get("id") else _clock(t)
            lines.append(f"| {o['video']} | {o['total']:.2f}s | " + " / ".join(f"{l['time']:.2f}" for l in o["laps"])
                         + f" | {at} | {'; '.join(o['problems']) or 'clean'} |")
        lines.append("")
    lines += ["## Edits in the footage", ""]
    for name, (jumps, how, _) in edits.items():
        if jumps is None:
            lines.append(f"- `{name}`: not checked ({how}): edits inside a lap can't be ruled out")
            continue
        cuts = [j for j in jumps if j["kind"] == "cut"]
        lines.append(f"- `{name}`: {how}; " + (f"{len(cuts)} edit(s) found" if cuts else "no edits found"))
        off = (src or {}).get("offset_s") or 0.0
        for j in cuts:
            lines.append(f"  - {_clock(off + j['frame'] / fps)}: timer {j['before']:.0f}s -> {j['after']:.0f}s "
                         f"({j['shift']:+.2f}s against the footage)")
    lines += ["", "Lap timing: crossings are matched visually to about +-3 frames. All laps: `laps.csv`; "
              "the full analysis: `report.md`.", ""]
    (work / "verify.md").write_text("\n".join(lines))
    log(f"  verification: {work / 'verify.md'}")


def verify(work, claim=None, tol=None, log=print):
    """Run the verification on an analysed work directory. `claim` is the --claim string."""
    work = Path(work)
    R = json.loads((work / "result.json").read_text())
    from .youtube import load_source
    src = load_source(work)
    c = parse_claim(claim)
    tol = tolerance((src or {}).get("fps") or R["fps"], tol)     # the upload's own frame rate, not the doubled one
    edits = {v["name"]: osd_edits(work, v["name"]) for v in R["videos"]}
    cuts = {n: [j for j in (e[0] or []) if j["kind"] == "cut"] for n, e in edits.items()}
    motion_armed = {v["name"] for v in R["videos"] if v["arm_source"].startswith("motion")}
    timers = {n: dict(jumps=e[0], spans=e[2]) for n, e in edits.items() if n in motion_armed}
    verdict, why, w, others = judge(R, c, tol, cuts, timers)
    n_cuts = sum(len(v) for v in cuts.values())
    if n_cuts and verdict == "not verifiable":
        why += f"; the footage has {n_cuts} edit(s) (see below), which can break laps apart"
    if w:
        vpath = next(v["path"] for v in R["videos"] if v["name"] == w["video"])
        box = json.loads((work / "features" / f"{w['video']}.json").read_text())["pic_box"]
        crossing_sheet(vpath, box, [w["laps"][0]["start"]] + [l["end"] for l in w["laps"]],
                       work / "sheets" / "verify_crossings.jpg",
                       f"{verdict.upper()}: {w['video']} {w['total']:.2f}s - each row one gate crossing (X)")
    write(work, R, c, tol, verdict, why, w, others, src, edits, log)
    out = dict(verdict=verdict, why=why, claim=c, tolerance_s=tol, source=src,
               reference_certain=reference_certainty(R, src)[1],
               chain=None if not w else dict(video=w["video"], total=w["total"], laps=[l["time"] for l in w["laps"]],
                                             frames=[w["laps"][0]["start"]] + [l["end"] for l in w["laps"]],
                                             problems=w["problems"], caveats=w["caveats"],
                                             split_notes=split_notes(w, c),
                                             crossings=[dict(label=a, frame=f, seconds=round(t, 3), link=u)
                                                        for a, f, t, u in crossings(w, R["fps"], src)]),
               edits={n: (e[0], e[1]) for n, e in edits.items()})
    (work / "verify.json").write_text(json.dumps(out, indent=1))
    log(f"  VERDICT: {verdict.upper()} - {why}")
    return out


def cannot_time(work, claim, error, log=print):
    """verify.md / verify.json when the analysis itself failed (e.g. no reference lap could be found)."""
    from .youtube import load_source
    work, src = Path(work), load_source(Path(work))
    why = (f"the laps could not be timed: {str(error).rstrip('.')}. An upload is usually one video, often without a parked "
           "start: pass --anchor VIDEO:FRAME on the start-gate pass that begins the run (from the clip's own "
           "lap-timer overlay, or the gate pass in the opening seconds). For your own uploads, --readme or "
           "--track with the profile of the same build works too; never use one from another pilot's room")
    title = f"Video: [{src.get('title') or src['id']}]({src['url']})\n\n" if src else ""
    (work / "verify.md").write_text(f"# Run verification\n\n{title}## Verdict: **NOT VERIFIABLE**\n\n"
                                    f"{why[0].upper() + why[1:]}.\n")
    (work / "verify.json").write_text(json.dumps(dict(verdict="not verifiable", why=why, claim=parse_claim(claim),
                                                      source=src, chain=None), indent=1))
    log(f"  VERDICT: NOT VERIFIABLE - {why}")
