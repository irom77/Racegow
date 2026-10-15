"""Pass 1: per-frame feature extraction (gate colour blobs, OSD timer cells, motion)."""
import cv2, numpy as np, pickle, sys, os, glob
from multiprocessing import Pool

SRC = '/path/to/videos'  # folder of hdz_*.mp4 recordings
OUT = 'work/feat'
# OSD timer strip (full-res, 1280x720); its x offset varies per recording
STRIP_Y0, STRIP_Y1, STRIP_X0, STRIP_X1 = 440, 536, 888, 1120
# 4:3 picture area and OSD masks (in half-res coords of the 4:3 crop, 480x360)
def osd_mask():
    m = np.ones((360, 480), np.uint8)
    m[:30, :] = 0          # top OSD line
    m[295:, :] = 0         # bottom OSD lines
    m[215:275, 0:120] = 0  # battery
    m[215:275, 365:480] = 0  # timers
    return m
MASK = osd_mask()

def blobs(mask, hsv, k):
    """Largest k blobs: (cx, cy, area, x, y, w, h, meanH, meanS, meanV)."""
    n, lab, st, cen = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return []
    order = np.argsort(-st[1:, 4])[:k] + 1
    out = []
    for i in order:
        x, y, w, h, a = st[i]
        if a < 3:
            break
        sel = lab[y:y + h, x:x + w] == i
        mh, ms, mv = (float(hsv[y:y + h, x:x + w, c][sel].mean()) for c in range(3))
        out.append((float(cen[i][0]), float(cen[i][1]), int(a), int(x), int(y), int(w), int(h), mh, ms, mv))
    return out

def run(path):
    cv2.setNumThreads(2)
    name = os.path.basename(path)[:-4]
    dst = f'{OUT}/{name}.pkl'
    if os.path.exists(dst):
        return name
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    red, yel, cells, motion, bright, thumbs = [], [], [], [], [], []
    prev = None
    i = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        pic = cv2.resize(fr[:, 160:1120], (480, 360), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(pic, cv2.COLOR_BGR2HSV)
        h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        # loose thresholds; per-blob mean HSV is kept so detection can be tightened offline
        rm = (((h < 10) | (h > 165)) & (s > 80) & (v > 60)).astype(np.uint8) * MASK
        ym = ((h >= 18) & (h <= 45) & (s > 50) & (v > 80)).astype(np.uint8) * MASK
        red.append(blobs(rm, hsv, 10))
        yel.append(blobs(ym, hsv, 8))
        small = cv2.resize(pic, (80, 60), interpolation=cv2.INTER_AREA)
        thumbs.append(small)
        g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.int16)
        motion.append(0.0 if prev is None else float(np.abs(g - prev).mean()))
        bright.append(float(g.mean()))
        prev = g
        if i % 3 == 0:
            gray = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
            cells.append(np.packbits(gray[STRIP_Y0:STRIP_Y1, STRIP_X0:STRIP_X1] > 190))
        i += 1
    pickle.dump(dict(name=name, fps=fps, n=i, red=red, yel=yel, motion=np.array(motion),
                     bright=np.array(bright), cells=np.array(cells)), open(dst, 'wb'))
    np.save(f'{OUT}/{name}_thumbs.npy', np.array(thumbs))
    return name

if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    files = sorted(glob.glob(f'{SRC}/*.mp4'))
    if len(sys.argv) > 1:
        files = [f for f in files if any(a in f for a in sys.argv[1:])]
    with Pool(min(11, len(files))) as p:
        for n in p.imap_unordered(run, files):
            print('done', n, flush=True)
