"""Pass 2: laps from start-gate crossings.

1. Arm segments from the OSD fly timer (OCR): the timer ticks at 1 s/s only while armed.
2. Lap candidates: subsequence DTW of each video against a verified reference lap (gate -> gate).
3. Each lap boundary is refined to an exact 60 fps crossing frame by matching the gate approach
   (frames leading up to the reference crossings) at full frame rate.
4. A lap is clean when its DTW cost is low (it looks like the reference lap all the way round, so
   no crash / detour), it lies inside one armed segment (no disarm), and the quad never stalls.
5. Best = minimum sum of 3 consecutive clean laps (shared crossings) across all videos."""
import sys, glob, os, json, pickle
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(__file__))
from osd import read_timers
from lapdtw import descriptors, lap_matches, STEP

FEAT = 'work/feat'
CENT = np.load('work/cent_all.npy')
FPS = 60.0
OCR_STEP = 3
REF_VIDEO, REF_CROSS = 'hdz_0024', (963, 1596)   # verified start-gate crossings (top bar leaves frame)
DTW_MAX = 0.62            # candidate laps
CLEAN_COST = 0.35         # clean laps: whole lap matches the reference lap closely
LAP_MIN, LAP_MAX = 7.0, 15.0
STALL_MOTION, STALL_SECS = 1.5, 0.5
APPROACH = list(range(-30, 7, 3))   # frames around a crossing used for fine alignment
SEARCH = 45                         # +- frames searched around a DTW boundary

def arm_segments(feat):
    secs, _ = read_timers(feat, CENT)
    fly = secs[:, 0]
    t = np.arange(len(fly)) * OCR_STEP / FPS
    off = fly - t
    segs, cur = [], None
    for k in np.where(~np.isnan(off))[0]:
        nb = off[max(0, k - 6):k + 7]; nb = nb[~np.isnan(nb)]
        if abs(off[k] - np.median(nb)) > 1.5:
            continue                                   # OCR glitch
        if cur and abs(off[k] - cur[2]) <= 1.3 and k - cur[1] <= 40:
            cur[1] = k; cur[2] = 0.9 * cur[2] + 0.1 * off[k]
        else:
            if cur: segs.append(cur)
            cur = [k, k, off[k]]
    if cur: segs.append(cur)
    # an OCR dropout splits a run without the timer actually stopping: same offset, short gap -> merge
    merged = []
    for sg in segs:
        if merged and (sg[0] - merged[-1][1]) * OCR_STEP / FPS < 1.0 and abs(sg[2] - merged[-1][2]) < 1.5:
            merged[-1][1] = sg[1]
        else:
            merged.append(list(sg))
    return [(a * OCR_STEP, b * OCR_STEP + OCR_STEP - 1) for a, b, _ in merged if (b - a) * OCR_STEP / FPS >= 3.0]

def fine_desc(thumbs):
    """Full-rate 80x60 normalised grey descriptors (OSD masked) for crossing refinement."""
    keep = np.ones((60, 80), bool)
    keep[:5, :] = False; keep[50:, :] = False; keep[36:46, 60:] = False; keep[36:46, :20] = False
    g = (thumbs[..., 0] * 0.11 + thumbs[..., 1] * 0.59 + thumbs[..., 2] * 0.3).astype(np.float32)[:, keep]
    g -= g.mean(1, keepdims=True); g /= g.std(1, keepdims=True) + 1e-6
    return g

def refine(F, approx, refs):
    """Exact crossing frame near `approx`: best mean correlation of the approach window to any reference."""
    D = F.shape[1]
    best, bf = -9, approx
    lo = max(-min(APPROACH), approx - SEARCH); hi = min(len(F) - max(APPROACH) - 1, approx + SEARCH)
    for c in range(lo, hi + 1):
        win = F[[c + o for o in APPROACH]]
        sc = max(float(np.mean(np.sum(win * R, 1))) / D for R in refs)
        if sc > best:
            best, bf = sc, c
    return bf, best

def stalled(motion, a, b):
    w = int(STALL_SECS * FPS)
    m = motion[a:b]
    if len(m) < w: return False
    return bool(np.convolve(m, np.ones(w) / w, 'valid').min() < STALL_MOTION)

def analyze(name, ref):
    feat = pickle.load(open(f'{FEAT}/{name}.pkl', 'rb'))
    thumbs = np.load(f'{FEAT}/{name}_thumbs.npy')
    X = descriptors(thumbs)
    F = fine_desc(thumbs)
    segs = arm_segments(feat)
    matches = lap_matches(X, ref['T'], DTW_MAX)
    # boundaries -> refined crossings (merge boundaries that refine to the same crossing)
    cache = {}
    def cross(i):
        if i not in cache:
            cache[i] = refine(F, i * STEP, ref['approach'])
        return cache[i]
    laps = []
    for s, e, cost in matches:
        (a, sa), (b, sb) = cross(s), cross(e)
        laps.append(dict(video=name, start=a, end=b, time=(b - a) / FPS, cost=cost, gate_fit=(sa, sb)))
    # snap nearly-shared boundaries of adjacent laps onto one crossing
    laps.sort(key=lambda l: l['start'])
    for p, q in zip(laps, laps[1:]):
        if abs(q['start'] - p['end']) <= 30:
            q['start'] = p['end']; q['time'] = (q['end'] - q['start']) / FPS
    def seg_of(f):
        return next((i for i, (a, b) in enumerate(segs) if a <= f <= b), None)
    for l in laps:
        reasons = []
        if l['cost'] > CLEAN_COST: reasons.append(f"lap doesn't match reference (cost {l['cost']:.2f})")
        sa, sb = seg_of(l['start']), seg_of(l['end'])
        if sa is None or sa != sb: reasons.append('disarmed during lap')
        if not (LAP_MIN <= l['time'] <= LAP_MAX): reasons.append(f"duration {l['time']:.2f}s")
        if stalled(feat['motion'], l['start'], l['end']): reasons.append('stall/crash')
        l['clean'] = not reasons; l['reason'] = '; '.join(reasons)
    return dict(video=name, segments=segs, laps=laps)

def best_three(results):
    best = None
    for r in results:
        L = r['laps']
        for i in range(len(L) - 2):
            trio = L[i:i + 3]
            if all(l['clean'] for l in trio) and trio[0]['end'] == trio[1]['start'] and trio[1]['end'] == trio[2]['start']:
                tot = (trio[2]['end'] - trio[0]['start']) / FPS
                if best is None or tot < best['total']:
                    best = dict(video=r['video'], laps=trio, total=tot)
    return best

def load_ref():
    th = np.load(f'{FEAT}/{REF_VIDEO}_thumbs.npy')
    X = descriptors(th); F = fine_desc(th)
    a, b = REF_CROSS
    return dict(T=X[a // STEP:b // STEP + 1], approach=[F[[c + o for o in APPROACH]] for c in REF_CROSS])

if __name__ == '__main__':
    ref = load_ref()
    names = sorted(os.path.basename(p)[:-4] for p in glob.glob(f'{FEAT}/hdz_*.pkl'))
    if len(sys.argv) > 1: names = [n for n in names if n in sys.argv[1:]]
    results = []
    for n in names:
        r = analyze(n, ref); results.append(r)
        print(f"\n== {n}: armed " + ', '.join(f'{a/FPS:.1f}-{b/FPS:.1f}' for a, b in r['segments']))
        for l in r['laps']:
            print(f"   {l['start']/FPS:7.2f} -> {l['end']/FPS:7.2f}  {l['time']:6.2f}s  cost {l['cost']:.2f}  fit {l['gate_fit'][0]:.2f}/{l['gate_fit'][1]:.2f}  {'CLEAN' if l['clean'] else l['reason']}")
    b = best_three(results)
    print('\nBEST 3 CONSECUTIVE:', None if b is None else
          f"{b['video']} total {b['total']:.2f}s laps {[round(l['time'], 2) for l in b['laps']]} "
          f"frames {b['laps'][0]['start']}..{b['laps'][2]['end']}")
    json.dump(dict(results=results, best=b), open('work/analysis.json', 'w'), indent=1, default=float)
