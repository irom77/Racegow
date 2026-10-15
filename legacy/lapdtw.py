"""Lap detection by subsequence DTW against a reference lap (start-gate crossing -> next crossing).

Each frame becomes a small normalised grey descriptor (OSD masked). The reference lap is aligned
anywhere in a flight with open begin/end; the end of a good alignment is a start-gate crossing and
its begin is the previous crossing, so a lap match carries its own duration."""
import numpy as np, cv2

STEP = 3                 # analyse at 20 Hz
DW, DH = 32, 24

def descriptors(thumbs):
    th = thumbs[::STEP]
    out = []
    keep = np.ones((60, 80), bool)
    keep[:5, :] = False; keep[50:, :] = False; keep[36:46, 60:] = False; keep[36:46, :20] = False
    for im in th:
        g = cv2.cvtColor(np.ascontiguousarray(im), cv2.COLOR_BGR2GRAY).astype(np.float32)
        g[~keep] = np.nan
        g = np.where(np.isnan(g), np.nanmean(g), g)   # neutral fill so blur doesn't smear OSD
        g = cv2.GaussianBlur(g, (5, 5), 1.5)
        g = cv2.resize(g, (DW, DH), interpolation=cv2.INTER_AREA).ravel()
        g -= g.mean(); g /= g.std() + 1e-6
        out.append(g)
    return np.array(out, np.float32)

def subseq_dtw(X, T):
    """X: (N,D) flight descriptors, T: (M,D) reference lap. Steps (1,1),(1,2),(2,1) => speed 0.5x..2x.
    Returns per-end-index mean cost and start index of the best path ending there."""
    N, M = len(X), len(T)
    C = 1.0 - (X @ T.T) / X.shape[1]                     # (N,M) cost in [0,2]
    INF = 1e9
    D = np.full((N, M), INF, np.float32)
    S = np.zeros((N, M), np.int32)                       # path start (i index)
    D[:, 0] = C[:, 0]; S[:, 0] = np.arange(N)
    for i in range(1, N):
        # candidate predecessors for j>=1
        a = D[i - 1, :-1]                                # (i-1, j-1)
        sa = S[i - 1, :-1]
        b = np.full(M - 1, INF, np.float32); sb = np.zeros(M - 1, np.int32)
        b[1:] = D[i - 1, :-2] + C[i, 1:-1]; sb[1:] = S[i - 1, :-2]   # (i-1, j-2): skipped template cell still paid
        if i >= 2:
            c = D[i - 2, :-1] + 0.5 * (C[i - 1, 1:] - C[i, 1:])   # (i-2, j-1): extra flight frame, cell averaged
            sc = S[i - 2, :-1]
        else:
            c = np.full(M - 1, INF, np.float32); sc = sa
        best = np.minimum(np.minimum(a, b), c)
        sel = np.where(best == a, sa, np.where(best == b, sb, sc))
        D[i, 1:] = best + np.where(best == c, 0.5, 1.0) * C[i, 1:] if False else best + C[i, 1:]
        S[i, 1:] = sel
    return D[:, -1] / M, S[:, -1]

def lap_matches(X, T, thr):
    """Non-overlapping lap alignments with mean cost <= thr: list of (start_i, end_i, cost)."""
    cost, start = subseq_dtw(X, T)
    order = np.argsort(cost)
    used = np.zeros(len(X), bool)
    out = []
    for e in order:
        if cost[e] > thr:
            break
        s = start[e]
        # laps may share their boundary crossing; only interiors must not overlap
        if used[s + 3:e - 2].any():
            continue
        used[s + 3:e - 2] = True
        out.append((int(s), int(e), float(cost[e])))
    return sorted(out)
