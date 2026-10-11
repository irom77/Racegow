"""Pass 1 — one sequential decode per video. Cached per video in <work>/features/.

Stores, for every frame: an 80x60 thumbnail of the camera picture (pillarbox removed) and the
frame-to-frame motion; every OCR_STEP frames: the binarised digit cells of each OSD timer."""
import json
import os
from multiprocessing import Pool
from pathlib import Path
import numpy as np
import cv2
from . import osd
from .config import THUMB_W, THUMB_H, OCR_STEP, CALIB_SAMPLES
from .media import video_info


def calibrate(path, info):
    """Picture box (non-black area) and OSD timer positions from frames sampled across the video."""
    cap = cv2.VideoCapture(str(path))
    grays, colmax, rowmax = [], None, None
    for k in range(CALIB_SAMPLES):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int((k + 0.5) * info["n"] / CALIB_SAMPLES))
        ok, fr = cap.read()
        if not ok:
            continue
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        grays.append(g)
        c, r = g.mean(0), g.mean(1)
        colmax = c if colmax is None else np.maximum(colmax, c)
        rowmax = r if rowmax is None else np.maximum(rowmax, r)
    cap.release()
    if not grays:
        raise RuntimeError(f"cannot decode {path}")
    cols, rows = np.where(colmax > 16)[0], np.where(rowmax > 16)[0]
    box = [int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1] if len(cols) and len(rows) \
        else [0, 0, info["w"], info["h"]]
    timers = osd.locate_timers(grays)
    return dict(pic_box=box, timers=[list(map(float, t)) for t in timers])


def extract_one(args):
    path, out_dir = args
    path, out_dir = Path(path), Path(out_dir)
    name = path.stem
    meta_p = out_dir / f"{name}.json"
    if meta_p.exists():
        return name, "cached"
    cv2.setNumThreads(2)
    info = video_info(path)
    cal = calibrate(path, info)
    x0, y0, x1, y1 = cal["pic_box"]
    cap = cv2.VideoCapture(str(path))
    thumbs = np.lib.format.open_memmap(out_dir / f"{name}.thumbs.tmp.npy", mode="w+", dtype=np.uint8,
                                       shape=(max(info["n"], 1) + 64, THUMB_H, THUMB_W, 3))
    motion, cells = [], []
    prev = None
    i = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if i >= thumbs.shape[0]:
            break
        small = cv2.resize(fr[y0:y1, x0:x1], (THUMB_W, THUMB_H), interpolation=cv2.INTER_AREA)
        thumbs[i] = small
        g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.int16)
        motion.append(0.0 if prev is None else float(np.abs(g - prev).mean()))
        prev = g
        if i % OCR_STEP == 0 and cal["timers"]:
            gray = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
            cells.append(np.packbits(np.stack([osd.grab_cells(gray, t) for t in cal["timers"]])))
        i += 1
    cap.release()
    n = i
    final = np.lib.format.open_memmap(out_dir / f"{name}.thumbs.npy", mode="w+", dtype=np.uint8,
                                      shape=(n, THUMB_H, THUMB_W, 3))
    final[:] = thumbs[:n]
    del final, thumbs
    os.remove(out_dir / f"{name}.thumbs.tmp.npy")
    np.savez_compressed(out_dir / f"{name}.feat.npz", motion=np.array(motion, np.float32),
                        cells=np.array(cells) if cells else np.zeros((0, 0), np.uint8))
    meta = dict(video=str(path), name=name, fps=info["fps"], n=n, width=info["w"], height=info["h"], **cal)
    meta_p.write_text(json.dumps(meta, indent=1))
    return name, f"{n} frames, {len(cal['timers'])} OSD timer(s)"


def extract_all(videos, work, workers=None):
    out = Path(work) / "features"
    out.mkdir(parents=True, exist_ok=True)
    workers = workers or max(1, min(len(videos), (os.cpu_count() or 2) // 3))
    with Pool(workers) as p:
        for name, msg in p.imap_unordered(extract_one, [(str(v), str(out)) for v in videos]):
            print(f"  [extract] {name}: {msg}", flush=True)
    return out


def load(work, name):
    d = Path(work) / "features"
    meta = json.loads((d / f"{name}.json").read_text())
    z = np.load(d / f"{name}.feat.npz")
    meta["motion"] = z["motion"]
    meta["thumbs"] = np.load(d / f"{name}.thumbs.npy", mmap_mode="r")
    nt = len(meta["timers"])
    if nt and z["cells"].size:
        ch, cw = osd.CELL_H + 2 * osd.PAD, osd.CELL_W + 2 * osd.PAD
        bits = np.unpackbits(z["cells"], axis=1)[:, :nt * 4 * ch * cw]
        meta["cells"] = bits.reshape(-1, nt, 4, ch, cw)
    else:
        meta["cells"] = None
    return meta
