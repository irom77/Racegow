"""Scan: one decode per video -> per-0.1 s motion features + 1 Hz thumbnails, cached as <work>/scan/<video>.npz.

HDZero (and most DVRs) record at a constant bitrate, so packet sizes say nothing about motion: every
frame is decoded (PyAV, multi-threaded) and every `fps/10`-th frame is kept as a small grey image.
Between consecutive samples a dense optical flow is fitted with a similarity transform:

  speed     |translation|          camera panning / flying fast across the scene
  roll      |rotation| (rad)       rolls and flips
  zoom      |scale - 1|            diving / punching straight ahead
  parallax  flow the fit misses    things passing close to the camera (gaps, trees, near misses)
  diff      mean |frame - frame|   any change at all (0 = parked, menu, frozen picture)
  osd       static text mid-picture  Betaflight's post-flight STATS screen (disarmed, often being carried),
                                     warnings, menus: strong edges in the picture centre that stay put

Plus picture checks per sample (brightness, contrast, neighbour-pixel correlation: random static has
almost none) and the audio level. PyAV is used rather than an ffmpeg binary: the static ffmpeg 7.0.2
build segfaults on HDZero .ts recordings, PyAV's bundled libav reads them fine."""
import os
import sys
import time
from pathlib import Path

import numpy as np
import cv2

SAMPLE_HZ = 10
GRAY_W, GRAY_H = 160, 90          # sample size before cropping to the picture area
THUMB_W, THUMB_H = 128, 72        # 1 Hz colour thumbnails (contact sheets, scene diversity)
DECODE_THREADS = 3
VIDEO_EXT = (".mp4", ".mov", ".ts", ".mkv", ".avi")


def list_videos(folder):
    folder = Path(folder)
    if not folder.is_dir():
        raise SystemExit(f"Not a folder: {folder}")
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in VIDEO_EXT and p.is_file())


def active_box(grays, thr=24):
    """Picture area inside black bars (4:3 HDZero picture in a 16:9 frame), from the median image over
    time: OSD text drawn over the bars is sparse in time and drops out of the median, a max would keep it."""
    if not grays:
        return 0, 0, GRAY_W, GRAY_H
    m = np.median(np.stack(grays[:: max(1, len(grays) // 120)]), axis=0)
    h, w = m.shape
    cols = np.flatnonzero(m.mean(axis=0) > thr)
    rows = np.flatnonzero(m.mean(axis=1) > thr)
    if len(cols) < w // 3 or len(rows) < h // 3:
        return 0, 0, w, h
    return int(cols[0]), int(rows[0]), int(cols[-1] + 1), int(rows[-1] + 1)


def _grid(w, h, step=4, margin=6):
    ys, xs = np.mgrid[margin:h - margin:step, margin:w - margin:step]
    return xs.ravel().astype(np.float32), ys.ravel().astype(np.float32)


def motion(g0, g1, grid):
    """Similarity fit of the dense flow g0 -> g1: (speed px, |rotation| rad, |scale-1|, residual px)."""
    flow = cv2.calcOpticalFlowFarneback(g0, g1, None, 0.5, 3, 11, 3, 5, 1.1, 0)
    xs, ys = grid
    u = flow[ys.astype(int), xs.astype(int), 0]
    v = flow[ys.astype(int), xs.astype(int), 1]
    cx, cy = xs.mean(), ys.mean()
    x, y = xs - cx, ys - cy
    # u = a*x - b*y + tx ; v = b*x + a*y + ty
    n = len(x)
    A = np.zeros((2 * n, 4), np.float32)
    A[:n, 0], A[:n, 1], A[:n, 2] = x, -y, 1
    A[n:, 0], A[n:, 1], A[n:, 3] = y, x, 1
    rhs = np.concatenate([u, v])
    p, *_ = np.linalg.lstsq(A, rhs, rcond=None)
    res = rhs - A @ p
    resid = float(np.median(np.hypot(res[:n], res[n:])))
    scale = 1.0 + p[0]
    return float(np.hypot(p[2], p[3])), float(abs(np.arctan2(p[1], scale))), float(abs(scale - 1)), resid


def static_text(c0, c1):
    """Share of the picture centre (at 640x360) that is a strong vertical edge in both samples and
    unchanged between them: OSD text standing still over a moving or still picture. Flight: ~0.001,
    Betaflight STATS screen: 0.025-0.05."""
    e0 = np.abs(cv2.Sobel(c0, cv2.CV_16S, 1, 0)) > 200
    e1 = np.abs(cv2.Sobel(c1, cv2.CV_16S, 1, 0)) > 200
    same = np.abs(c0.astype(np.int16) - c1.astype(np.int16)) < 10
    return float((e0 & e1 & same).mean())


def picture_stats(g):
    f = g.astype(np.float32)
    a, b = f[:, :-1].ravel(), f[:, 1:].ravel()
    sd = float(f.std())
    corr = float(np.corrcoef(a, b)[0, 1]) if sd > 1 else 1.0
    return float(f.mean()), sd, corr


def scan_video(path, out):
    import av
    cv2.setNumThreads(1)          # one worker per video already; nested thread pools thrash (5x slower)
    t0 = time.time()
    c = av.open(str(path))
    vs = c.streams.video[0]
    vs.thread_type = "AUTO"
    fps = float(vs.average_rate or vs.guessed_rate or 60)
    step = max(1, round(fps / SAMPLE_HZ))
    every_s = max(1, round(fps))
    streams = [vs] + ([c.streams.audio[0]] if c.streams.audio else [])
    grays, thumbs, aud, centres = [], [], [], []
    n = 0
    vt0 = None
    for pkt in c.demux(*streams):
        try:
            frames = pkt.decode()
        except av.error.FFmpegError:
            continue
        for fr in frames:
            if pkt.stream.type == "audio":
                if fr.time is None:
                    continue
                a = fr.to_ndarray().astype(np.float32)
                if a.dtype.kind == "i" or np.abs(a).max() > 2:
                    a = a / 32768.0
                aud.append((fr.time, float(np.sqrt(np.mean(a * a))), fr.samples / max(fr.sample_rate, 1)))
                continue
            if vt0 is None:
                vt0 = fr.time or 0.0
            if n % step == 0:
                grays.append(fr.reformat(width=GRAY_W, height=GRAY_H, format="gray").to_ndarray().copy())
                centres.append(fr.reformat(width=640, height=360, format="gray").to_ndarray()[100:260, 160:480].copy())
            if n % every_s == 0:
                thumbs.append(fr.reformat(width=THUMB_W, height=THUMB_H, format="bgr24").to_ndarray().copy())
            n += 1
    c.close()
    if n < fps * 2:
        np.savez_compressed(out, ok=False, frames=n, fps=fps)
        return dict(name=Path(path).stem, ok=False, frames=n, seconds=n / fps)

    x0, y0, x1, y1 = active_box(grays)
    crop = [g[y0:y1, x0:x1] for g in grays]
    h, w = crop[0].shape
    grid = _grid(w, h)
    m = len(crop)
    feats = np.zeros((m, 9), np.float32)   # speed roll zoom parallax diff bright contrast corr osd
    for i, g in enumerate(crop):
        feats[i, 5:8] = picture_stats(g)
        if i:
            feats[i, 0:4] = motion(crop[i - 1], g, grid)
            feats[i, 4] = float(np.abs(g.astype(np.int16) - crop[i - 1].astype(np.int16)).mean())
            feats[i, 8] = static_text(centres[i - 1], centres[i])
    feats[0, :5] = feats[1, :5] if m > 1 else 0
    # audio level per sample slot
    lvl = np.zeros(m, np.float32)
    if aud:
        at = np.array([a[0] for a in aud]) - (vt0 or 0.0)
        av_ = np.array([a[1] for a in aud])
        idx = np.clip((at * fps / step).astype(int), 0, m - 1)
        np.maximum.at(lvl, idx, av_)
    np.savez_compressed(out, ok=True, fps=fps, step=step, frames=n, feats=feats, audio=lvl,
                        thumbs=np.stack(thumbs), box=np.array([x0, y0, x1, y1]) / [GRAY_W, GRAY_H, GRAY_W, GRAY_H],
                        has_audio=bool(aud))
    return dict(name=Path(path).stem, ok=True, frames=n, seconds=n / fps, took=time.time() - t0)


def _job(args):
    path, out = args
    try:
        return scan_video(path, out)
    except Exception as e:   # unreadable / truncated recording: skip, keep going (cached as unusable)
        np.savez_compressed(out, ok=False, error=str(e))
        return dict(name=Path(path).stem, ok=False, error=f"{type(e).__name__}: {e}")


def scan_all(videos, work, workers=None):
    """Scan every video not cached yet. Returns {name: path} of usable videos."""
    from multiprocessing import get_context
    sd = Path(work) / "scan"
    sd.mkdir(parents=True, exist_ok=True)
    todo = [(str(v), str(sd / f"{v.stem}.npz")) for v in videos if not (sd / f"{v.stem}.npz").exists()]
    if todo:
        workers = workers or max(1, min(len(todo), (os.cpu_count() or 4) // DECODE_THREADS))
        size = sum(Path(v).stat().st_size for v, _ in todo) / 1e9
        print(f"  scanning {len(todo)} video(s), {size:.1f} GB, {workers} worker(s); cached in {sd}", flush=True)
        t0 = time.time()
        with get_context("fork").Pool(workers) as pool:
            for i, r in enumerate(pool.imap_unordered(_job, todo), 1):
                tag = (f"{r['seconds']:.0f} s" if r.get("ok") else
                       f"skipped, {r.get('error') or 'shorter than 2 s'}")
                print(f"  [{i}/{len(todo)}] {r['name']}: {tag}  ({time.time() - t0:.0f} s elapsed)", flush=True)
    good = {}
    for v in videos:
        f = sd / f"{v.stem}.npz"
        if f.exists():
            with np.load(f) as z:
                if bool(z["ok"]):
                    good[v.stem] = v
    return good


if __name__ == "__main__":
    print(scan_video(sys.argv[1], sys.argv[2]))
