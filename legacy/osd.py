"""OSD timer OCR: locate the timer block (x offset varies per recording) and read mm:ss for both rows."""
import numpy as np, cv2

H, W = 96, 232
ROW_Y = [(6, 36), (60, 90)]
DIGIT_DX = [-71, -39, 25, 57]   # cell left edge relative to colon centre
CW = 18

def strips(feat):
    return np.unpackbits(feat['cells'], axis=1)[:, :H * W].reshape(-1, H, W)

def colon_x(S):
    """Colon centre column: the narrow always-on 2-dot column pair in the long-run mean image."""
    m = S.mean(0)
    best, bx = -1, None
    for x in range(100, 200):
        col = m[6:36, x - 2:x + 3]
        side = m[6:36, x - 6:x - 3].sum() + m[6:36, x + 4:x + 7].sum()
        sc = col[4:10].sum() + col[22:28].sum() - col[12:20].sum() - side
        if sc > best:
            best, bx = sc, x
    return bx

def cells(S, cx):
    out = np.zeros((len(S), 2, 4, 30, CW), np.uint8)
    for r, (y0, y1) in enumerate(ROW_Y):
        for c, dx in enumerate(DIGIT_DX):
            out[:, r, c] = S[:, y0:y1, cx + dx:cx + dx + CW]
    return out

# k-means centres (work/cent_all.npy, built from timer cells of every video) hand-labelled
# by inspecting each cluster's medoid. None = blank / clutter / partial glyph.
CENT_LABELS = dict(enumerate([
    0, 1, 2, 0, 4, 2, None, 3, 2, 5, 4, 5, 3, 7, 0, 0, 6, 0, 3, 8,
    0, 0, 0, 4, 6, 4, 1, 4, 7, 1, 2, 0, 1, 0, 0, 1, 8, 0, 0, None,
    2, 5, 2, 3, None, 0, 0, 0, 9, 5, 0, 9, None, None, 4, None, 0, 2, 0, 3]))

def classify(cellarr, cent, maxdist=0.12):
    """cellarr: (..., 30, CW) binary -> digit labels (-1 = unknown)."""
    flat = cellarr.reshape(-1, 30 * CW).astype(np.float32)
    d = ((flat ** 2).sum(1)[:, None] + (cent ** 2).sum(1)[None] - 2 * flat @ cent.T) / flat.shape[1]
    k = d.argmin(1)
    lab = np.array([CENT_LABELS[int(i)] if CENT_LABELS[int(i)] is not None else -1 for i in k])
    lab[d[np.arange(len(k)), k] > maxdist] = -1
    return lab.reshape(cellarr.shape[:-2])

def read_timers(feat, cent):
    """Seconds for each OSD timer row per sampled frame (NaN when unreadable)."""
    S = strips(feat)
    cx = colon_x(S)
    dig = classify(cells(S, cx), cent)          # (N, 2, 4)
    ok = (dig >= 0).all(2) & (dig[:, :, 2] <= 5)
    secs = (dig[:, :, 0] * 10 + dig[:, :, 1]) * 60 + dig[:, :, 2] * 10 + dig[:, :, 3]
    return np.where(ok, secs, np.nan), cx
