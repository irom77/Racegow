"""Start-gate pass detection by matching the approach *sequence* against reference passes."""
import numpy as np

REF_VIDEO = 'hdz_0016'
REF_CENTERS = [612, 4854, 6952, 7817]   # verified clean passes; centre ~11 frames before crossing
OFFSETS = [-18, -12, -6, 0, 6]
CROSS_AFTER_CENTER = 11                  # frames from centre to the top bar leaving the frame

def prep(th):
    g = (th[..., 0] * 0.11 + th[..., 1] * 0.59 + th[..., 2] * 0.3).astype(np.float32)
    keep = np.ones(g.shape[1:], bool)
    keep[:5, :] = False; keep[50:, :] = False; keep[36:46, 60:] = False; keep[36:46, :20] = False
    g = g[:, keep]
    g -= g.mean(1, keepdims=True)
    g /= g.std(1, keepdims=True) + 1e-6
    return g

def seq_score(G, refs_G):
    """G: prepped frames (N,D). refs_G: prepped reference thumbs (N_ref,D). Returns (N,) score, best-ref index."""
    N, D = G.shape
    best = np.full(N, -1.0, np.float32)
    which = np.zeros(N, int)
    for ri, c in enumerate(REF_CENTERS):
        parts = []
        for o in OFFSETS:
            s = G @ refs_G[c + o] / D                       # sim of every frame to this ref frame
            # tolerate +-4 frames of speed variation: running max
            sm = np.lib.stride_tricks.sliding_window_view(np.pad(s, 4, constant_values=-1), 9).max(1)
            parts.append(np.roll(sm, -o))                   # align so index = candidate centre
        sc = np.mean(parts, 0)
        upd = sc > best
        best[upd] = sc[upd]; which[upd] = ri
    return best, which
