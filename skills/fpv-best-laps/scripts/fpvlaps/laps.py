"""Lap matching: picture descriptors, subsequence DTW against a reference lap, 60 fps crossing refinement."""
import numpy as np
import cv2
from .config import DTW_STEP, REFINE_WINDOW, REFINE_SEARCH, THUMB_W, THUMB_H


def _keep_mask():
    """Ignore the thumbnail border bands where OSD text lives (top line, bottom lines, side widgets)."""
    k = np.ones((THUMB_H, THUMB_W), bool)
    k[:5, :] = False
    k[50:, :] = False
    k[36:46, 60:] = False
    k[36:46, :20] = False
    return k


KEEP = _keep_mask()


KEEP2 = KEEP[::2, ::2]


def fine_desc(thumbs, chunk=4096):
    """60 fps descriptors: grey thumbnail pooled to 40x30, OSD bands masked, normalised."""
    out = np.empty((len(thumbs), int(KEEP2.sum())), np.float32)
    for i in range(0, len(thumbs), chunk):
        t = np.asarray(thumbs[i:i + chunk]).astype(np.float32)
        g = t[..., 0] * 0.11 + t[..., 1] * 0.59 + t[..., 2] * 0.3
        g = g.reshape(len(g), THUMB_H // 2, 2, THUMB_W // 2, 2).mean((2, 4))
        out[i:i + chunk] = g[:, KEEP2]
    g = out
    g -= g.mean(1, keepdims=True)
    g /= g.std(1, keepdims=True) + 1e-6
    return g


def dtw_desc(thumbs):
    """Coarse descriptors for DTW (every DTW_STEP-th frame, blurred 32x24) — tolerant to small path offsets."""
    out = []
    for im in thumbs[::DTW_STEP]:
        g = cv2.cvtColor(np.ascontiguousarray(im), cv2.COLOR_BGR2GRAY).astype(np.float32)
        g[~KEEP] = np.nan
        g = np.where(np.isnan(g), np.nanmean(g), g)
        g = cv2.GaussianBlur(g, (5, 5), 1.5)
        g = cv2.resize(g, (32, 24), interpolation=cv2.INTER_AREA).ravel()
        g -= g.mean()
        g /= g.std() + 1e-6
        out.append(g)
    return np.array(out, np.float32)


def subseq_dtw(X, T):
    """Open-begin/open-end DTW of reference lap T inside sequence X. Steps (1,1),(1,2),(2,1): the flight
    may run 0.5x..2x the reference speed. Every template cell is paid once, so cost/M is a mean cost."""
    N, M = len(X), len(T)
    C = 1.0 - (X @ T.T) / X.shape[1]
    INF = np.float32(1e9)
    D = np.full((N, M), INF, np.float32)
    S = np.zeros((N, M), np.int32)
    D[:, 0] = C[:, 0]
    S[:, 0] = np.arange(N)
    for i in range(1, N):
        a, sa = D[i - 1, :-1], S[i - 1, :-1]
        b = np.full(M - 1, INF, np.float32)
        sb = np.zeros(M - 1, np.int32)
        b[1:] = D[i - 1, :-2] + C[i, 1:-1]
        sb[1:] = S[i - 1, :-2]
        if i >= 2:
            c = D[i - 2, :-1] + 0.5 * (C[i - 1, 1:] - C[i, 1:])
            sc = S[i - 2, :-1]
        else:
            c, sc = np.full(M - 1, INF, np.float32), sa
        best = np.minimum(np.minimum(a, b), c)
        D[i, 1:] = best + C[i, 1:]
        S[i, 1:] = np.where(best == a, sa, np.where(best == b, sb, sc))
    return D[:, -1] / M, S[:, -1]


BOUNDARY_SLACK = 12                  # DTW steps (0.6 s at 20 Hz)


def lap_matches(X, T, max_cost):
    """Non-overlapping lap alignments (laps may share their boundary crossing): [(s, e, cost)] in DTW steps."""
    cost, start = subseq_dtw(X, T)
    used = np.zeros(len(X), bool)
    out = []
    for e in np.argsort(cost):
        if cost[e] > max_cost:
            break
        s = int(start[e])
        # adjacent laps share their boundary crossing and DTW ends are fuzzy by a few tenths of a
        # second, so only the interiors (minus ~0.6 s at each end) must not overlap
        if used[s + BOUNDARY_SLACK:e - BOUNDARY_SLACK].any():
            continue
        used[s + BOUNDARY_SLACK:e - BOUNDARY_SLACK] = True
        out.append((s, int(e), float(cost[e])))
    return sorted(out)


def window(F, c):
    idx = [c + o for o in REFINE_WINDOW]
    if idx[0] < 0 or idx[-1] >= len(F):
        return None
    return F[idx]


def refine(F, approx, refs):
    """Exact crossing frame near `approx`: best mean correlation of the +-0.5 s window around a candidate
    frame with the windows around the reference crossings."""
    D = F.shape[1]
    best, bf = -9.0, int(approx)
    lo = max(-min(REFINE_WINDOW), approx - REFINE_SEARCH)
    hi = min(len(F) - max(REFINE_WINDOW) - 1, approx + REFINE_SEARCH)
    for c in range(lo, hi + 1):
        w = F[[c + o for o in REFINE_WINDOW]]
        sc = max(float(np.sum(w * R)) / (D * len(REFINE_WINDOW)) for R in refs)
        if sc > best:
            best, bf = sc, c
    return bf, best


def stalled(motion, a, b, thr, secs, fps):
    w = max(1, int(secs * fps))
    m = motion[a:b]
    if len(m) < w:
        return False
    return bool(np.convolve(m, np.ones(w) / w, "valid").min() < thr)
