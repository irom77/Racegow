"""Sector splits and the theoretical best lap.

The reference lap is split into sectors (evenly by default, or at reference frames from `--sectors`
/ track.json). Every clean lap is already aligned to the reference lap by DTW, so each sector boundary
maps into each lap through the alignment path: a fixed-endpoint DTW of the lap against the reference
(20 Hz), then snapped to the exact frame against the consensus view of that point (the mean +-0.5 s
window over the mapped boundaries of the best-matching clean laps), the same way gate crossings are.
The theoretical best is the sum of the best time in each sector, from any clean laps."""
import statistics
import numpy as np
from .config import DTW_STEP, SECTORS_DEFAULT, SECTOR_REFINE_SEARCH
from .laps import refine, window

INF = np.float32(1e9)


def parse_spec(spec):
    """--sectors: '4' = split evenly into 4; '3800,4100' = boundaries at those reference frames.
    Returns ('even', n) or ('frames', [f1, f2, ...])."""
    vals = [int(x) for x in str(spec).replace(" ", "").split(",") if x]
    if len(vals) == 1 and 2 <= vals[0] <= 10:
        return "even", vals[0]
    if not vals or any(b <= a for a, b in zip(vals, vals[1:])):
        raise SystemExit(f"--sectors {spec}: give a count (2-10) or increasing reference-lap frames")
    return "frames", vals


def boundaries(ref, spec=None):
    """Interior sector boundaries as reference-video frames, and where they came from."""
    a, b = ref["start"], ref["end"]
    if spec is not None:
        kind, val = parse_spec(spec)
        how = "--sectors"
    elif ref.get("sectors"):
        kind, val, how = "frames", list(ref["sectors"]), "track profile"
    else:
        kind, val, how = "even", SECTORS_DEFAULT, "even split"
    if kind == "even":
        return [int(round(a + (b - a) * j / val)) for j in range(1, val)], how
    bad = [f for f in val if not a < f < b]
    if bad:
        raise SystemExit(f"sector boundaries {bad} are outside the reference lap ({ref['video']} frames {a}->{b})")
    return val, how


def align(X, T):
    """Fixed-endpoint DTW of a lap's descriptors X (N steps) against the reference T (M steps), steps
    (1,1), (1,2), (2,1). Returns, for every reference step m, the lap step aligned to it (float), or
    None when the lap is too short or long for the step pattern."""
    N, M = len(X), len(T)
    if N < 2 or M < 2 or not (M / 2 <= N <= 2 * M):
        return None
    C = 1.0 - (X @ T.T) / X.shape[1]
    D = np.full((N, M), INF, np.float32)
    B = np.zeros((N, M), np.int8)
    D[0, 0] = C[0, 0]
    for i in range(1, N):
        a = np.full(M, INF, np.float32)
        a[1:] = D[i - 1, :-1]                                    # (1,1)
        b = np.full(M, INF, np.float32)
        b[2:] = D[i - 1, :-2] + C[i, 1:-1]                       # (1,2) via (i, m-1)
        c = np.full(M, INF, np.float32)
        if i >= 2:
            c[1:] = D[i - 2, :-1] + C[i - 1, 1:]                 # (2,1) via (i-1, m)
        best = np.minimum(np.minimum(a, b), c)
        D[i] = np.minimum(best + C[i], INF)
        B[i] = np.where(best == a, 0, np.where(best == b, 1, 2))
    if D[-1, -1] >= INF:
        return None
    hits = [[] for _ in range(M)]
    i, m = N - 1, M - 1
    hits[m].append(i)
    while i > 0 or m > 0:
        step = B[i, m]
        if step == 0:
            i, m = i - 1, m - 1
        elif step == 1:
            hits[m - 1].append(i)
            i, m = i - 1, m - 2
        else:
            hits[m].append(i - 1)
            i, m = i - 2, m - 1
        hits[m].append(i)
    return [float(np.mean(h)) for h in hits]


def consensus(windows, max_n=40):
    if len(windows) < 3:
        return None
    W = np.mean(windows[:max_n], 0)
    W -= W.mean(1, keepdims=True)
    W /= W.std(1, keepdims=True) + 1e-6
    return W


def split(vids, laps, ref, T, spec=None, log=print):
    """Time every clean lap's sectors (adds lap['sectors'] in seconds and lap['sector_frames']) and
    return the summary for result.json, or None when there are no clean laps."""
    inner, how = boundaries(ref, spec)
    a0 = ref["start"] // DTW_STEP
    ms = [min(max(f // DTW_STEP - a0, 1), len(T) - 2) for f in inner]       # reference steps
    by_name = {v["name"]: v for v in vids}
    clean = sorted((l for l in laps if l["clean"] and l["video"] in by_name), key=lambda l: l["cost"])
    if not clean:
        return None
    mapped = []                                                             # (lap, [approx frames])
    for l in clean:
        v = by_name[l["video"]]
        s0 = l["start"] // DTW_STEP
        path = align(v["X"][s0:l["end"] // DTW_STEP + 1], T)
        if path is None:                                                    # proportional fallback
            fr = [l["start"] + (l["end"] - l["start"]) * (f - ref["start"]) / (ref["end"] - ref["start"])
                  for f in inner]
        else:
            fr = [(s0 + path[m]) * DTW_STEP for m in ms]
        mapped.append((l, [int(round(min(max(f, l["start"] + 1), l["end"] - 1))) for f in fr]))
    cons = []
    for k in range(len(inner)):
        ws = [w for l, fr in mapped if (w := window(by_name[l["video"]]["F"], fr[k])) is not None]
        cons.append(consensus(ws))
    fps = vids[0]["fps"]
    for l, fr in mapped:
        F = by_name[l["video"]]["F"]
        fr = [refine(F, f, [cons[k]], SECTOR_REFINE_SEARCH)[0] if cons[k] is not None else f
              for k, f in enumerate(fr)]
        edges = [l["start"]] + fr + [l["end"]]
        if any(q <= p for p, q in zip(edges, edges[1:])):
            continue                                                        # boundaries out of order
        l["sector_frames"] = [int(f) for f in fr]
        l["sectors"] = [round((q - p) / fps, 3) for p, q in zip(edges, edges[1:])]
    timed = [l for l in clean if "sectors" in l]
    if not timed:
        return None
    n = len(inner) + 1
    best_i = [min(range(len(timed)), key=lambda i: timed[i]["sectors"][k]) for k in range(n)]
    best = [timed[i]["sectors"][k] for k, i in enumerate(best_i)]
    real = min(timed, key=lambda l: l["time"])
    out = dict(count=n, boundaries=inner, source=how, laps_timed=len(timed),
               best=best, best_lap=[dict(video=timed[i]["video"], start=timed[i]["start"]) for i in best_i],
               median=[round(statistics.median(l["sectors"][k] for l in timed), 3) for k in range(n)],
               theoretical_best=round(sum(best), 3),
               best_real_lap=dict(video=real["video"], start=real["start"], time=real["time"]))
    log(f"  sectors ({how}): {n} at reference frames {inner}; theoretical best {out['theoretical_best']:.2f}s "
        f"vs best lap {real['time']:.2f}s ({len(timed)} clean laps timed)")
    return out


def sector_lines(R, top=10):
    """report.md section: sector table for the fastest clean laps, best per sector in bold."""
    S = R.get("sectors")
    if not S:
        return []
    fps = R["fps"]
    timed = [l for l in R["laps"] if l.get("sectors")]
    rank1 = R["best"][0]["laps"] if R.get("best") else []
    keys = {(l["video"], l["start"]) for l in rank1}
    show = sorted(timed, key=lambda l: l["time"])[:top]
    show += [l for l in timed if (l["video"], l["start"]) in keys and l not in show]
    show.sort(key=lambda l: l["time"])
    n = S["count"]
    ref = R["reference"]
    lines = ["## Sector splits", "",
             f"The reference lap (`{ref['video']}` {ref['start']} -> {ref['end']}) is split into {n} sectors at "
             f"frames {', '.join(map(str, S['boundaries']))} ({S['source']}). Each boundary is mapped into every "
             f"clean lap ({S['laps_timed']} timed) through its alignment with the reference lap. "
             "Fastest clean laps below; ★ = the best-3 result; **bold** = best in that sector.", "",
             "| Lap | " + " | ".join(f"S{k + 1}" for k in range(n)) + " | Lap time |",
             "|---|" + "---|" * (n + 1)]
    for l in show:
        cells = [f"**{t:.2f}**" if t == S["best"][k] else f"{t:.2f}" for k, t in enumerate(l["sectors"])]
        star = " ★" if (l["video"], l["start"]) in keys else ""
        lines.append(f"| {l['video']} @ {l['start'] / fps:.1f}s{star} | " + " | ".join(cells) + f" | {l['time']:.2f} |")
    real = S["best_real_lap"]["time"]
    lines += ["| *Median* | " + " | ".join(f"*{t:.2f}*" for t in S["median"]) + " | |",
              "| **Best sectors** | " + " | ".join(f"**{t:.2f}**" for t in S["best"])
              + f" | **{S['theoretical_best']:.2f}** |", "",
              f"**Theoretical best: {S['theoretical_best']:.2f}s** (best sectors from any clean laps) vs best real lap "
              f"{real:.2f}s: {real - S['theoretical_best']:.2f}s left on the table. Best sectors from: "
              + ", ".join(f"S{k + 1} {b['video']} @ {b['start'] / fps:.1f}s" for k, b in enumerate(S["best_lap"]))
              + ".", ""]
    if rank1 and all(l.get("sectors") for l in rank1):
        lost = [sum(l["sectors"][k] for l in rank1) - 3 * S["best"][k] for k in range(n)]
        k = int(np.argmax(lost))
        lines += [f"In the best-3 laps, most time vs the best sectors is lost in **S{k + 1}** "
                  f"(+{lost[k]:.2f}s over 3 laps; " + ", ".join(f"S{j + 1} +{t:.2f}s" for j, t in enumerate(lost))
                  + ").", ""]
    lines += ["Sector boundary views: `sheets/sectors.jpg` (move them with `--sectors F1,F2,...`, reference-lap "
              "frames, saved in track.json).", ""]
    return lines
