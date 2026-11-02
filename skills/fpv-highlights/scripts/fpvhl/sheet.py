"""Review sheets: sheets/picks.jpg (one row per chosen clip, 5 frames across it, real decoded frames)
and sheets/candidates.jpg (the 40 best windows, middle thumbnail each, picked ones outlined)."""
from pathlib import Path

import numpy as np
import cv2

from .media import frames_at
from .pick import mmss

TW, TH = 256, 144


def _label(img, text, color=(0, 255, 255), y=16, scale=0.45):
    cv2.putText(img, text, (5, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, text, (5, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def write_sheets(work, vids, res):
    sd = Path(work) / "sheets"
    sd.mkdir(exist_ok=True)
    rows = []
    for i, p in enumerate(res["clips"], 1):
        ts = np.linspace(p["start"] + 0.1, p["end"] - 0.2, 5)
        tiles = []
        for t, f in zip(ts, frames_at(p["path"], ts)):
            im = cv2.resize(f, (TW, TH), interpolation=cv2.INTER_AREA) if f is not None else np.zeros((TH, TW, 3), np.uint8)
            _label(im, mmss(t), y=TH - 8, color=(255, 255, 255), scale=0.4)
            tiles.append(im)
        head = np.zeros((TH, 150, 3), np.uint8)
        _label(head, f"#{i}", scale=0.7, y=26)
        _label(head, p["video"], y=52)
        _label(head, f"{mmss(p['start'])}-{mmss(p['end'])}", y=74, color=(255, 255, 255))
        _label(head, f"{p['end'] - p['start']:.1f} s  sc {p['score']:.2f}", y=96, color=(200, 200, 200))
        rows.append(np.hstack([head] + tiles))
    picks = sd / "picks.jpg"
    cv2.imwrite(str(picks), np.vstack(rows) if rows else np.zeros((10, 10, 3), np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 85])

    tiles = []
    for c in res["candidates"]:
        v = vids[c["video"]]
        th = v["thumbs"][min(len(v["thumbs"]) - 1, int((c["start"] + c["end"]) / 2))]
        im = cv2.resize(th, (TW, TH), interpolation=cv2.INTER_LINEAR)
        if c["picked"]:
            cv2.rectangle(im, (1, 1), (TW - 2, TH - 2), (0, 220, 0), 3)
        _label(im, f"{c['video']} {mmss(c['start'])}")
        _label(im, f"{c['score']:.2f}", y=TH - 8, color=(255, 255, 255), scale=0.4)
        tiles.append(im)
    while len(tiles) % 8:
        tiles.append(np.zeros((TH, TW, 3), np.uint8))
    cand = sd / "candidates.jpg"
    grid = np.vstack([np.hstack(tiles[i:i + 8]) for i in range(0, len(tiles), 8)]) if tiles else np.zeros((10, 10, 3), np.uint8)
    cv2.imwrite(str(cand), grid, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return picks, cand
