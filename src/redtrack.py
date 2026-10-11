"""Start-gate crossing from the red corner tape: a small saturated red blob that grows and sweeps
outward over several frames, then leaves the picture (the quad passes under the top bar)."""
import numpy as np

def is_tape(b):
    cx, cy, a, x, y, w, h, mh, ms, mv = b
    return 4 <= a <= 160 and ms >= 105 and (mh >= 160 or mh <= 8) and max(w, h) <= 3 * min(w, h) + 4

def tracks(red, max_jump=32):
    """Greedy nearest-neighbour tracking of tape blobs; returns list of [(frame, cx, cy, area), ...]."""
    active, done = [], []
    for f, blobs in enumerate(red):
        cand = [b for b in blobs if is_tape(b)]
        used = set()
        nxt = []
        for tr in active:
            lf, lx, ly, la = tr[-1]
            best, bi = None, None
            for k, b in enumerate(cand):
                if k in used:
                    continue
                dist = np.hypot(b[0] - lx, b[1] - ly)
                if dist <= max_jump * (f - lf) and (best is None or dist < best):
                    best, bi = dist, k
            if bi is not None:
                used.add(bi)
                b = cand[bi]
                tr.append((f, b[0], b[1], b[2]))
                nxt.append(tr)
            elif f - lf <= 2:          # tolerate a 2-frame dropout
                nxt.append(tr)
            else:
                done.append(tr)
        for k, b in enumerate(cand):
            if k not in used:
                nxt.append([(f, b[0], b[1], b[2])])
        active = nxt
    return done + active

def crossings(red, W=480, H=360):
    """Frames where a tape track ends by growing and exiting toward a frame edge."""
    out = []
    for tr in tracks(red):
        if len(tr) < 6:
            continue
        f0, x0, y0, a0 = tr[0]
        # crossing = outermost point of the track (robust to a glitchy last match)
        rr = [np.hypot(t[1] - W / 2, t[2] - H / 2) for t in tr]
        f1, x1, y1, a1 = tr[int(np.argmax(rr))]
        amax = max(t[3] for t in tr)
        grew = amax >= 2.0 * max(a0, 4) and amax >= 18
        # radial outward motion from the picture centre
        r0 = np.hypot(x0 - W / 2, y0 - H / 2)
        r1 = np.hypot(x1 - W / 2, y1 - H / 2)
        near_edge = x1 < 70 or x1 > W - 70 or y1 < 80
        if grew and r1 > r0 + 40 and near_edge and (f1 - f0) <= 90:
            out.append(dict(frame=f1 + 1, start=f0, amax=float(amax), x=float(x1), y=float(y1)))
    return sorted(out, key=lambda c: c['frame'])
