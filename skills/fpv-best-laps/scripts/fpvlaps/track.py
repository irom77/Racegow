"""Track calibration: learn the lap period and a reference lap that starts and ends at the start gate.

Nothing here is specific to one layout. The only assumption is the race format: every recording
begins with the quad parked in front of the start gate, so
  * the parked view is what the camera sees on the start line, just before the gate;
  * shortly after takeoff the quad flies through that gate, so the view just after takeoff is
    the view just after a gate crossing.
Each lap passes the same start line, so frames resembling the parked view mark candidate gate
approaches. Tracks often cross the gate's sightline elsewhere too (figure-8s), so a candidate only
counts as the gate when the following second also looks like the post-takeoff flight. The best pair of
consecutive gate events (about one lap period apart) becomes the reference lap; DTW against it
finds every other lap."""
import numpy as np
from .config import STILL_MOTION, FLIGHT_MOTION, PERIOD_RANGE_S, DTW_STEP
from .laps import lap_matches, refine, window


def smooth(x, n):
    return np.convolve(x, np.ones(n) / n, "same")


def takeoff(v, search_s=90.0):
    """(parked_start, parked_end, launch) for the race start, or None.

    Recordings begin with a few seconds of handling, then the quad sits on the start spot facing the
    start gate (props may idle, the pilot may hover in place) and then launches. The parked view is
    the longest stretch in the first `search_s` seconds whose frames all look alike. Launch is the
    first frame after it where the view leaves the parked view for good (stays different for 1 s)."""
    fps = v["fps"]
    F = v["F"][:int(search_s * fps)]
    if len(F) < 4 * fps:
        return None
    step = max(1, int(fps / 10))                                     # 10 Hz scan
    idx = np.arange(0, len(F), step)
    G = F[idx] @ F[idx].T / F.shape[1]
    best = None
    for i in range(len(idx)):                                         # longest run similar to its start frame
        j = i
        while j + 1 < len(idx) and G[i, j + 1] > 0.9:
            j += 1
        if (j - i) * step >= 2 * fps and (best is None or j - i > best[1] - best[0]):
            best = (i, j)
    if best is None:
        return None
    a, b = idx[best[0]], idx[best[1]]
    pd = F[a:b + 1].mean(0)
    pd /= pd.std() + 1e-6
    sim = smooth(v["F"] @ pd / F.shape[1], max(3, int(0.25 * fps)))
    hold = int(fps)
    for i in range(b, len(sim) - hold):
        if (sim[i:i + hold] < 0.85).all():
            return int(a), int(b), int(i)
    return None


def parked_template(vids):
    descs = []
    for v in vids:
        t = v.get("takeoff")
        if t:
            a, b, _ = t
            d = v["F"][a:b].mean(0)
            descs.append(d / (d.std() + 1e-6))
    if not descs:
        return None
    D = np.array(descs)
    sim = D @ D.T / D.shape[1]
    return D[int(np.argmax(sim.mean(1)))]                     # medoid: the common start line


def lap_period(vids):
    """Dominant lap period (s) from descriptor self-similarity across flights (10 Hz Gram diagonals)."""
    fps = vids[0]["fps"]
    sub = 2                                              # DTW rate / 2
    rate = fps / DTW_STEP / sub
    lags = np.arange(int(PERIOD_RANGE_S[0] * rate), int(PERIOD_RANGE_S[1] * rate))
    acc = np.zeros(len(lags))
    cnt = np.zeros(len(lags))
    for v in vids:
        X = v["X"][::sub]
        flying = (smooth(v["motion"], int(fps))[::DTW_STEP * sub] > FLIGHT_MOTION)[:len(X)]
        X = X[:len(flying)]
        G = (X @ X.T) / X.shape[1]
        for k, L in enumerate(lags):
            if L >= len(X):
                break
            ok = flying[:-L] & flying[L:]
            if ok.sum() < 10:
                continue
            acc[k] += np.diagonal(G, L)[ok].sum()
            cnt[k] += ok.sum()
    r = np.where(cnt > 0, acc / np.maximum(cnt, 1), -1)
    peaks = [k for k in range(2, len(r) - 2) if r[k] == r[k - 2:k + 3].max() and r[k] > -1]
    if not peaks:
        return None
    k = max(peaks, key=lambda k: r[k] - 0.5 * (r[max(0, k - 8):k + 9].min()))  # prominence
    return float(lags[k] / rate)


POST = np.arange(10, 91, 5)          # frames after a gate event compared with post-takeoff flight


def post_takeoff_score(v, c, vids):
    """How much the second after frame c looks like the second after a takeoff (= after the gate)."""
    F = v["F"]
    if c + POST[-1] >= len(F):
        return -1.0
    W = F[c + POST]
    best = -1.0
    for u in vids:
        t = u.get("takeoff")
        if not t or u is v and abs(t[2] - c) < 30:
            continue
        t0 = t[2]
        lo, hi = t0 - 20, t0 + 80 + POST[-1] + 1
        if lo < 0 or hi > len(u["F"]):
            continue
        M = W @ u["F"][lo:hi].T / F.shape[1]                      # (len(POST), hi-lo)
        ks = np.arange(0, 101, 2)[:, None]                          # takeoff-side shifts
        sc = M[np.arange(len(POST))[None, :], ks + POST[None, :]].mean(1)
        best = max(best, float(sc.max()))
    return best


def gate_candidates(v, tmpl, period_frames, vids):
    F, fps = v["F"], v["fps"]
    s = F @ tmpl / F.shape[1]
    flying = smooth(v["motion"], int(0.3 * fps)) > FLIGHT_MOTION * 0.75
    s = np.where(flying, s, -1)
    half = max(10, int(0.25 * period_frames))
    cands = []
    for i in range(len(s)):
        if s[i] > 0.4 and s[i] == s[max(0, i - half):i + half].max():
            cands.append(dict(frame=i, park=float(s[i]), post=post_takeoff_score(v, i, vids)))
    return cands


def calibrate(vids, log=print):
    """Returns a track profile dict, or raises with a message telling the agent what to do."""
    for v in vids:
        v["takeoff"] = takeoff(v)
    tmpl = parked_template(vids)
    if tmpl is None:
        raise RuntimeError("No parked start found in any video (expected the quad to sit still before "
                           "takeoff). Pass --anchor VIDEO:FRAME with a start-gate crossing.")
    P = lap_period(vids)
    if P is None:
        raise RuntimeError("Could not find a repeating lap pattern. Pass --anchor VIDEO:FRAME.")
    fps = vids[0]["fps"]
    Pf = P * fps
    log(f"  lap period ~{P:.2f}s; parked start found in {sum(1 for v in vids if v['takeoff'])}/{len(vids)} videos")
    allc = []
    for v in vids:
        for c in gate_candidates(v, tmpl, Pf, vids):
            c["video"] = v["name"]
            c["score"] = c["park"] + c["post"]
            allc.append(c)
    if not allc:
        raise RuntimeError("No start-line views found during flight. Pass --anchor VIDEO:FRAME.")
    thr = np.percentile([c["score"] for c in allc], 60)
    by_video = {}
    for c in allc:
        by_video.setdefault(c["video"], []).append(c)
    pairs = []
    for name, cs in by_video.items():
        v = next(u for u in vids if u["name"] == name)
        for a in cs:
            if a["score"] < thr:
                continue
            for b in cs:
                gap = b["frame"] - a["frame"]
                if 0.75 * Pf <= gap <= 1.35 * Pf and b["score"] >= thr and same_segment(v, a["frame"], b["frame"]):
                    pairs.append((a["score"] + b["score"], v, a["frame"], b["frame"]))
    if not pairs:
        raise RuntimeError("No clean lap between two start-line views. Pass --anchor VIDEO:FRAME.")
    pairs.sort(key=lambda p: -p[0])
    return pick_reference(vids, pairs[:8], P, log)


def same_segment(v, a, b):
    return any(s <= a and b <= e for s, e in v["segments"])


def build_reference(v, c0, c1):
    F = v["F"]
    # snap c1 onto the exact frame that best matches c0's surroundings
    c1, _ = refine(F, c1, [window(F, c0)])
    return dict(video=v["name"], start=int(c0), end=int(c1))


def reference_arrays(vids, ref):
    v = next(u for u in vids if u["name"] == ref["video"])
    a, b = ref["start"], ref["end"]
    T = v["X"][a // DTW_STEP:b // DTW_STEP + 1]
    wins = [w for w in (window(v["F"], a), window(v["F"], b)) if w is not None]
    return T, wins


def endpoint_match(v, a, b):
    """Correlation of the +-0.5 s around both ends of a lap: a real lap starts and ends at the same place."""
    wa, wb = window(v["F"], a), window(v["F"], b)
    if wa is None or wb is None:
        return -1.0
    return float(np.sum(wa * wb) / wa.size)


def pick_reference(vids, pairs, P, log):
    """Among candidate laps, keep the one that starts and ends at the same place, has a typical length
    and explains the other videos best. The start line itself is fixed afterwards (takeoff_phase)."""
    best = None
    for _, v, a, b in pairs:
        ref = build_reference(v, a, b)
        e = endpoint_match(v, ref["start"], ref["end"])
        dur = (ref["end"] - ref["start"]) / v["fps"]
        if e < 0.6:
            log(f"  reference candidate {ref['video']} {ref['start']}->{ref['end']} rejected: ends differ ({e:.2f})")
            continue
        T, _ = reference_arrays(vids, ref)
        costs = []
        for u in vids:
            costs += [c for _, _, c in lap_matches(u["X"], T, 0.62)]
        if len(costs) < 3:
            continue
        q = float(np.median(sorted(costs)[:max(3, len(costs) // 2)]))   # quality of the better half
        score = q + 0.3 * abs(dur - P) / P - 0.1 * e
        log(f"  reference candidate {ref['video']} {ref['start']}->{ref['end']} ({dur:.2f}s): "
            f"{len(costs)} laps, cost {q:.3f}, ends match {e:.2f}")
        if best is None or score < best[0]:
            best = (score, ref, v)
    if best is None:
        raise RuntimeError("Reference lap candidates did not match other laps. Pass --anchor VIDEO:FRAME.")
    ref = shift_to_start_line(vids, best[2], best[1], P, log)
    ref["period_s"] = P
    ref["source"] = "auto"
    return ref


def takeoff_phase(vids, v, ref, log):
    """Where on the reference lap does a takeoff begin? The quad is parked on the racing line just before
    the start gate, so a takeoff flies the opening of a lap, only slower. Each takeoff's first 3 s
    (compressed 1-3x to absorb the slow start) is DTW-aligned into the reference lap cycle (doubled
    to allow wrap-around); the aligned start is the start line. Returns frames after ref start."""
    from .laps import subseq_dtw
    T = v["X"][ref["start"] // DTW_STEP:ref["end"] // DTW_STEP + 1]
    M = len(T)
    X2 = np.concatenate([T, T])
    rate = v["fps"] / DTW_STEP
    votes = []
    for u in vids:
        t = u.get("takeoff")
        if not t:
            continue
        q0 = t[2] // DTW_STEP
        Q = u["X"][q0:q0 + int(3 * rate)]
        if len(Q) < int(2 * rate):
            continue
        best = None
        for sub in (1, 2, 3):
            q = Q[::sub]
            cost, start = subseq_dtw(X2, q)
            e = int(np.argmin(cost))
            if best is None or cost[e] < best[0]:
                best = (float(cost[e]), int(start[e]) % M)
        votes.append(best)
    if not votes:
        log("  no takeoff to locate the start line; reference lap kept as found")
        return 0
    votes.sort()
    keep = [s for _, s in votes[:max(1, (len(votes) + 1) // 2)]]      # better-aligned half
    ang = np.array(keep) / M * 2 * np.pi                                 # circular median-ish
    phase = (np.angle(np.mean(np.exp(1j * ang))) % (2 * np.pi)) / (2 * np.pi) * M
    log(f"  start line from {len(votes)} takeoff(s): {phase * DTW_STEP / v['fps']:.2f}s into the reference lap")
    return int(round(phase * DTW_STEP))


def shift_to_start_line(vids, v, ref, P, log):
    off = takeoff_phase(vids, v, ref, log)
    L = ref["end"] - ref["start"]
    if off > L / 2:
        off -= L                                         # shift backwards instead
    c0 = ref["start"] + off
    c1 = ref["end"] + off
    if abs(off) < 3 or c0 < 60 or c1 >= len(v["F"]) - 60:
        return ref
    new = build_reference(v, c0, c1)
    e = endpoint_match(v, new["start"], new["end"])
    if e < 0.6 or not same_segment(v, new["start"], new["end"]):
        log(f"  could not move the reference onto the start line (ends match {e:.2f}); keeping {ref['start']}->{ref['end']}")
        return ref
    log(f"  reference moved onto the start line: {new['start']}->{new['end']} "
        f"({(new['end'] - new['start']) / v['fps']:.2f}s, ends match {e:.2f})")
    return new


def reference_from_anchor(vids, name, frame, log=print):
    """Manual anchor: a start-gate crossing frame; the lap end is found one lap period later."""
    v = next((u for u in vids if u["name"] == name), None)
    if v is None:
        raise RuntimeError(f"--anchor video {name} not found")
    P = lap_period(vids) or 10.0
    Pf = int(P * v["fps"])
    F = v["F"]
    w0 = window(F, frame)
    best, bf = -9, None
    for c in range(frame + int(0.7 * Pf), min(len(F) - 40, frame + int(1.4 * Pf))):
        w = window(F, c)
        if w is None:
            break
        sc = float(np.sum(w * w0))
        if sc > best:
            best, bf = sc, c
    if bf is None:
        raise RuntimeError("anchor too close to the end of the video")
    ref = dict(video=name, start=int(frame), end=int(bf), period_s=P, source="anchor")
    log(f"  reference from anchor: {name} {frame}->{bf} ({(bf - frame) / v['fps']:.2f}s)")
    return ref
