"""OSD timer location and reading (Betaflight-style mm:ss timers, anywhere on screen).

Timers are found per video from persistent white glyphs: each timer has a ':' whose two dots are a
fixed distance apart. That distance sets the glyph scale, so the same digit templates work for any
recording resolution or OSD position. One timer is enough; extra ones are kept as alternatives."""
import numpy as np
import cv2
from .config import ASSETS, OSD_WHITE

# geometry at the template scale (colon dot spacing = 18.1 px on 720p HDZero recordings)
REF_DOT_DY = 18.1
CELL_H, CELL_W = 30, 18
DIGIT_DX = (-70.5, -38.5, 25.5, 57.5)  # cell left edges relative to the colon centre (mm:ss): a 32 px
                                       # character pitch, centred 2.5 px right of the colon
WIDE_PITCHES = tuple(range(34, 45))    # other character pitches some OSDs use with the same glyphs
                                       # (seen: 40 px on other pilots' HDZero uploads)

_T = np.load(ASSETS / "osd_digits.npz")
_CENTERS, _LABELS = _T["centers"], _T["labels"]


def find_colons(persist, region_xy):
    """persist: mean of binarised glyph masks over sampled frames (region only).
    Returns colon candidates [(cx, cy, dy)] in full-frame coordinates."""
    H = persist.shape[0]
    m = (persist > 0.6).astype(np.uint8)
    n, _, st, cen = cv2.connectedComponentsWithStats(m, 8)
    dots = [(cen[i][0], cen[i][1], st[i][4]) for i in range(1, n)
            if st[i][2] <= 0.03 * H + 3 and st[i][3] <= 0.03 * H + 3 and 4 <= st[i][4] <= 0.004 * H * H + 20]
    out = []
    for i, a in enumerate(dots):
        for b in dots[i + 1:]:
            top, bot = (a, b) if a[1] < b[1] else (b, a)
            dy = bot[1] - top[1]
            if abs(a[0] - b[0]) <= 2.5 and 6 <= dy <= 0.09 * H and 0.5 <= a[2] / b[2] <= 2.0:
                out.append(((a[0] + b[0]) / 2 + region_xy[0], (a[1] + b[1]) / 2 + region_xy[1], dy))
    return out


PAD = 2                               # margin around each cell so OCR can absorb +-2 px misalignment


def digit_dx(colon):
    """Cell left edges for a timer: (cx, cy, dy) uses the default layout, (cx, cy, dy, pitch) a wider one."""
    if len(colon) < 4:
        return DIGIT_DX
    return tuple(2.5 + colon[3] * m - CELL_W / 2 for m in (-2, -1, 1, 2))


def cell_boxes(colon):
    """(x, y, w, h) of the 4 digit cells including the PAD margin, in full-frame pixels."""
    cx, cy, dy = colon[:3]
    s = dy / REF_DOT_DY
    h, w = (CELL_H + 2 * PAD) * s, (CELL_W + 2 * PAD) * s
    return [(int(round(cx + (dx - PAD) * s)), int(round(cy - h / 2)), int(round(w)), int(round(h))) for dx in digit_dx(colon)]


def grab_cells(gray, colon):
    """4 binary cells (CELL_H+2*PAD x CELL_W+2*PAD) of one mm:ss timer."""
    out = np.zeros((4, CELL_H + 2 * PAD, CELL_W + 2 * PAD), np.uint8)
    H, W = gray.shape
    for k, (x, y, w, h) in enumerate(cell_boxes(colon)):
        if x < 0 or y < 0 or x + w > W or y + h > H:
            continue
        c = (gray[y:y + h, x:x + w] > OSD_WHITE).astype(np.uint8)
        out[k] = cv2.resize(c, (CELL_W + 2 * PAD, CELL_H + 2 * PAD), interpolation=cv2.INTER_NEAREST)
    return out


def classify(cells, maxdist=0.12):
    """cells (..., CELL_H+2*PAD, CELL_W+2*PAD) -> digit labels, -1 = unreadable.
    Each cell is matched at every +-PAD shift and the best-fitting alignment wins."""
    lead = cells.shape[:-2]
    flat = cells.reshape(-1, CELL_H + 2 * PAD, CELL_W + 2 * PAD).astype(np.float32)
    c2 = (_CENTERS ** 2).sum(1)[None]
    best_d = np.full(len(flat), np.inf, np.float32)
    best_k = np.zeros(len(flat), int)
    for oy in range(2 * PAD + 1):
        for ox in range(2 * PAD + 1):
            f = flat[:, oy:oy + CELL_H, ox:ox + CELL_W].reshape(len(flat), -1)
            d = ((f ** 2).sum(1)[:, None] + c2 - 2 * f @ _CENTERS.T) / f.shape[1]
            k = d.argmin(1)
            dk = d[np.arange(len(k)), k]
            upd = dk < best_d
            best_d[upd], best_k[upd] = dk[upd], k[upd]
    lab = _LABELS[best_k].astype(int)
    lab[best_d > maxdist] = -1
    return lab.reshape(lead)


def to_seconds(digits):
    """digits (..., 4) -> mm:ss in seconds, NaN when unreadable."""
    ok = (digits >= 0).all(-1) & (digits[..., 2] <= 5)
    secs = (digits[..., 0] * 10 + digits[..., 1]) * 60 + digits[..., 2] * 10 + digits[..., 3]
    return np.where(ok, secs, np.nan)


def locate_timers(gray_samples, max_timers=3, min_rate=0.3, min_distinct=3):
    """Find the mm:ss timers anywhere in the frame. A candidate must read as a valid mm:ss in at least
    `min_rate` of the samples and show at least `min_distinct` different values (a running timer,
    not static text such as a voltage). Returns up to `max_timers` colons sorted top->bottom, left->right.

    Only when the default layout finds no timer at all are wider character pitches tried
    (WIDE_PITCHES; such timers come back as (cx, cy, dy, pitch)). Those must also run like a clock
    over the samples, which are in video order: e.g. a link-quality "28:100" reads as mm:ss too."""
    persist = np.mean([g > OSD_WHITE for g in gray_samples], 0)
    cols = find_colons(persist, (0, 0))

    def score(col):
        secs = to_seconds(classify(np.stack([grab_cells(g, col) for g in gray_samples])))
        ok = ~np.isnan(secs)
        rate = float(np.mean(ok))
        return rate, secs, rate >= min_rate and len(np.unique(secs[ok])) >= min_distinct

    scored = []
    for col in cols:
        rate, _, good = score(col)
        if good:
            scored.append((rate, col))
    if not scored:
        for col in cols:
            best = None
            for q in WIDE_PITCHES:
                rate, secs, good = score((*col, float(q)))
                if good and runs_forward(secs) and (best is None or rate > best[0]):
                    best = (rate, (*col, float(q)))
            if best:
                scored.append(best)
    # de-duplicate (same colon found twice) and keep the most readable
    scored.sort(key=lambda t: -t[0])
    keep = []
    for rate, col in scored:
        if all(abs(col[0] - k[0]) > 4 or abs(col[1] - k[1]) > 4 for k in keep):
            keep.append(col)
        if len(keep) == max_timers:
            break
    return sorted(keep, key=lambda c: (c[1], c[0]))


def runs_forward(secs, min_rank_corr=0.7):
    """Readings (in video order) trend upward like a timer: Spearman rank correlation with the sample
    order. Isolated OCR misreads barely move it; a link-quality or other fluctuating value has none."""
    k = np.where(~np.isnan(secs))[0]
    if len(k) < 5:
        return False
    v = secs[k]
    if len(np.unique(v)) < 3:
        return False
    rv = np.argsort(np.argsort(v, kind="stable"), kind="stable").astype(float)
    rk = np.arange(len(k), dtype=float)
    if rv.std() == 0:
        return False
    return bool(np.corrcoef(rv, rk)[0, 1] >= min_rank_corr)


def arm_segments(secs, fps, step):
    """Armed runs of a per-arm timer: it ticks at 1 s/s only while armed, freezes when disarmed and
    resets on re-arm. Returns [(start_frame, end_frame)]."""
    t = np.arange(len(secs)) * step / fps
    off = secs - t
    segs, cur = [], None
    for k in np.where(~np.isnan(off))[0]:
        nb = off[max(0, k - 6):k + 7]
        nb = nb[~np.isnan(nb)]
        if abs(off[k] - np.median(nb)) > 1.5:
            continue                                   # single OCR glitch
        if cur and abs(off[k] - cur[2]) <= 1.3 and k - cur[1] <= 40:
            cur[1] = k
            cur[2] = 0.9 * cur[2] + 0.1 * off[k]
        else:
            if cur:
                segs.append(cur)
            cur = [k, k, off[k]]
    if cur:
        segs.append(cur)
    merged = []                                        # OCR dropout without the timer stopping
    for sg in segs:
        if merged and (sg[0] - merged[-1][1]) * step / fps < 1.0 and abs(sg[2] - merged[-1][2]) < 1.5:
            merged[-1][1] = sg[1]
        else:
            merged.append(list(sg))
    return [(int(a * step), int(b * step + step - 1)) for a, b, _ in merged if (b - a) * step / fps >= 3.0]
