"""Render the picked clips into one short with PyAV (H.264 + AAC MP4).

Layouts:
  fit   1080x1920: the whole picture, full width, over a blurred and dimmed fill of itself (default)
  crop  1080x1920: the picture cropped to 9:16 and scaled to fill
  wide  1920x1080: landscape, the picture full height over a blurred fill
Hard cuts between clips (the usual FPV edit), 0.3 s fade from black at the start and to black at the
end, 15 ms audio fades at every cut so nothing clicks. Clips at another frame rate are retimed to the
short's frame rate (the rate most of the short is recorded at, at most 60) by nearest frame."""
import itertools
import json
import shutil
from fractions import Fraction
from pathlib import Path

import numpy as np
import cv2

from .media import frames_between, audio_between
from .pick import mmss

RATE = 48000
MAX_FPS = 60          # YouTube plays at most 60 fps; HDZero 90 fps footage is retimed to 60
SIZES = dict(fit=(1080, 1920), crop=(1080, 1920), wide=(1920, 1080))


def picture_box(frames):
    """Picture area (black bars removed) in pixels, from the median of a clip's first frames."""
    small = [cv2.cvtColor(cv2.resize(f, (320, 180), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
             for f in frames]
    from .scan import active_box
    x0, y0, x1, y1 = active_box(small)
    h, w = frames[0].shape[:2]
    sx, sy = w / 320, h / 180
    x0, x1 = int(np.ceil(x0 * sx)) + 2, int(x1 * sx) - 2     # 2 px in: the bar edge is soft
    y0, y1 = (int(np.ceil(y0 * sy)) + 2, int(y1 * sy) - 2) if y0 > 0 or y1 < 180 else (0, h)
    if x1 - x0 < w // 3:
        return 0, 0, w, h
    return x0 // 2 * 2, y0 // 2 * 2, x1 // 2 * 2, y1 // 2 * 2


def _cover(img, W, H):
    h, w = img.shape[:2]
    s = max(W / w, H / h)
    r = cv2.resize(img, (max(W, int(round(w * s))), max(H, int(round(h * s)))), interpolation=cv2.INTER_LINEAR)
    y, x = (r.shape[0] - H) // 2, (r.shape[1] - W) // 2
    return r[y:y + H, x:x + W]


def _blur_fill(pic, W, H):
    small = _cover(cv2.resize(pic, (pic.shape[1] // 4, pic.shape[0] // 4), interpolation=cv2.INTER_AREA), W // 8, H // 8)
    small = cv2.convertScaleAbs(cv2.GaussianBlur(small, (0, 0), 6), alpha=0.45)
    return cv2.resize(small, (W, H), interpolation=cv2.INTER_LINEAR)


def compose(pic, layout, title_layer=None):
    W, H = SIZES[layout]
    if layout == "crop":
        out = _cover(pic, W, H)
    else:
        out = _blur_fill(pic, W, H)
        h, w = pic.shape[:2]
        s = min(W / w, H / h)
        nw, nh = int(round(w * s)) // 2 * 2, int(round(h * s)) // 2 * 2
        fg = cv2.resize(pic, (nw, nh), interpolation=cv2.INTER_LINEAR if s > 1 else cv2.INTER_AREA)
        x, y = (W - nw) // 2, (H - nh) // 2
        out[y:y + nh, x:x + nw] = fg
    if title_layer is not None:
        img, alpha, (r0, r1) = title_layer
        band = out[r0:r1].astype(np.float32)
        out[r0:r1] = (band * (1 - alpha) + img * alpha).astype(np.uint8)
    return out


def title_layer(text, layout):
    """Title in the top band (above the picture in the fit layout, top-left otherwise)."""
    if not text:
        return None
    W, H = SIZES[layout]
    img = np.zeros((H, W, 3), np.uint8)
    mask = np.zeros((H, W), np.uint8)
    font = cv2.FONT_HERSHEY_DUPLEX
    scale = 2.0 if layout != "wide" else 1.4
    lines = [text]
    while cv2.getTextSize(lines[-1], font, scale, 3)[0][0] > W - 120 and " " in lines[-1]:
        words = lines[-1].split(" ")
        cut = len(words) - 1
        while cut > 1 and cv2.getTextSize(" ".join(words[:cut]), font, scale, 3)[0][0] > W - 120:
            cut -= 1
        lines[-1:] = [" ".join(words[:cut]), " ".join(words[cut:])]
    lh = int(cv2.getTextSize("Ag", font, scale, 3)[0][1] * 1.7)
    y = (H - int(W * 3 / 4)) // 2 - 60 - lh * (len(lines) - 1) if layout == "fit" else 90
    for ln in lines:
        tw = cv2.getTextSize(ln, font, scale, 3)[0][0]
        x = (W - tw) // 2 if layout != "wide" else 60
        cv2.putText(mask, ln, (x, y), font, scale, 255, 12, cv2.LINE_AA)
        cv2.putText(img, ln, (x, y), font, scale, (255, 255, 255), 3, cv2.LINE_AA)
        y += lh
    alpha = cv2.GaussianBlur(mask, (0, 0), 3).astype(np.float32) / 255 * 0.55
    text_px = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) > 0
    alpha[text_px] = 1.0
    rows = np.flatnonzero(alpha.max(axis=1) > 0.004)
    r0, r1 = int(rows[0]), int(rows[-1]) + 1
    return img[r0:r1].astype(np.float32), alpha[r0:r1, :, None], (r0, r1)


def clip_frames(work, p, fps, n):
    """n frames of one clip retimed to `fps` (nearest source frame), picture area only. Streams (a clip
    is never held in memory) after a 12-frame look-ahead for the picture box."""
    it = frames_between(p["path"], p["start"], p["end"] + 1.0)
    head = list(itertools.islice(it, 12))
    if not head:
        return
    x0, y0, x1, y1 = picture_box([f for _, f in head])
    it = itertools.chain(head, it)
    cur = next(it)
    nxt = next(it, None)
    for k in range(n):
        tk = p["start"] + k / fps
        while nxt is not None and abs(nxt[0] - tk) <= abs(cur[0] - tk):
            cur, nxt = nxt, next(it, None)
        yield cur[1][y0:y1, x0:x1]


def list_or_pad(gen, n, black, p):
    """Exactly n frames: the clip's, then its last frame (or black if nothing could be read)."""
    last, k = None, 0
    for f in gen:
        last = f
        k += 1
        yield f
    if k == 0:
        print(f"  warning: no frames read for {p['video']} {mmss(p['start'])}; filled with black")
    for _ in range(n - k):
        yield last if last is not None else black


def render(work, layout="fit", title=None, music=None, music_volume=-10.0, save_to="default"):
    import av
    work = Path(work)
    res = json.loads((work / "picks.json").read_text())
    clips = res["clips"]
    fps_w = {}
    for p in clips:
        fps_w[round(p["fps"])] = fps_w.get(round(p["fps"]), 0) + p["end"] - p["start"]
    fps = min(MAX_FPS, max(fps_w, key=fps_w.get))
    W, H = SIZES[layout]
    exp = work / "export"
    exp.mkdir(exist_ok=True)
    total = sum(round((p["end"] - p["start"]) * fps) for p in clips) / fps
    folder = Path(res["videos_dir"]).name
    out = exp / f"short_{folder}_{layout}_{total:.0f}s.mp4"
    tl = title_layer(title, layout)

    oc = av.open(str(out), "w")
    vs = oc.add_stream("libx264", rate=fps)
    vs.width, vs.height, vs.pix_fmt = W, H, "yuv420p"
    vs.options = {"crf": "19", "preset": "veryfast", "profile": "high"}
    ast = oc.add_stream("aac", rate=RATE)
    ast.layout = "stereo"
    ast.bit_rate = 192000
    fade_n = int(0.3 * fps)
    total_n = int(round(total * fps))
    vi, ai = 0, 0
    timeline = []
    for ci, p in enumerate(clips):
        n = int(round((p["end"] - p["start"]) * fps))
        timeline.append(dict(video=p["video"], start=p["start"], end=p["end"], at=round(vi / fps, 2)))
        print(f"  clip {ci + 1}/{len(clips)}: {p['video']} {mmss(p['start'])}-{mmss(p['end'])}", flush=True)
        black = np.zeros((H // 2, W // 2, 3), np.uint8)
        for f in list_or_pad(clip_frames(work, p, fps, n), n, black, p):
            img = compose(f, layout, tl)
            if vi < fade_n:
                img = (img * (vi / fade_n)).astype(np.uint8)
            elif vi >= total_n - fade_n:
                img = (img * max(0.0, (total_n - 1 - vi) / fade_n)).astype(np.uint8)
            vf = av.VideoFrame.from_ndarray(img, format="bgr24")
            vf.pts = vi
            vf.time_base = Fraction(1, fps)
            for pkt in vs.encode(vf):
                oc.mux(pkt)
            vi += 1
        a = audio_between(p["path"], p["start"], p["start"] + n / fps, RATE)
        k = min(len(a) // 2, int(0.015 * RATE))
        if k:
            ramp = np.linspace(0, 1, k, dtype=np.float32)[:, None]
            a[:k] *= ramp
            a[-k:] *= ramp[::-1]
        if ci == 0:
            k2 = min(len(a), int(0.3 * RATE))
            a[:k2] *= np.linspace(0, 1, k2, dtype=np.float32)[:, None]
        if ci == len(clips) - 1:
            k2 = min(len(a), int(0.4 * RATE))
            a[-k2:] *= np.linspace(1, 0, k2, dtype=np.float32)[:, None]
        for i in range(0, len(a), 1024):
            chunk = np.ascontiguousarray(a[i:i + 1024].T)
            af = av.AudioFrame.from_ndarray(chunk, format="fltp", layout="stereo")
            af.sample_rate = RATE
            af.pts = ai
            for pkt in ast.encode(af):
                oc.mux(pkt)
            ai += chunk.shape[1]
    for pkt in vs.encode(None):
        oc.mux(pkt)
    for pkt in ast.encode(None):
        oc.mux(pkt)
    oc.close()

    mus = None
    if music:
        mus = _music(out, music, total, music_volume, exp)
    meta = dict(output=str(out.resolve()), layout=layout, size=[W, H], fps=fps, seconds=round(total, 2),
                title=title, music=mus, clips=timeline, videos_dir=res["videos_dir"])
    (exp / "render.json").write_text(json.dumps(meta, indent=1))
    print(f"  exported {out}  ({W}x{H}, {fps} fps, {total:.1f} s)")
    if save_to:
        save_copy(work, None if save_to == "default" else save_to)
    return out


def _music(out, music, secs, volume, exp):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "fpv-best-laps" / "scripts"))
    from fpvlaps.music import synth_track, mix_music
    if music == "auto":
        track = exp / "music.wav"
        mus = synth_track(secs, track)
    else:
        track, mus = Path(music), dict(file=str(music))
        if not track.is_file():
            raise SystemExit(f"Music file not found: {music}")
    mixed = out.with_suffix(".music.mp4")
    mix_music(out, track, mixed, secs, music_db=volume)
    mixed.replace(out)
    mus["music_volume_db"] = volume
    return mus


def default_save_dir(videos_dir):
    v = Path(videos_dir)
    return v.parent / "fpv-shorts" / v.name


def check_save_dir(dest, videos_dir):
    d = Path(dest).expanduser().resolve()
    s = Path(videos_dir).resolve()
    if d == s or s in d.parents:
        raise SystemExit(f"--save-to {dest} is inside the recordings folder {s}, which is deleted after "
                         "publishing; pick a folder outside it")
    return d


def save_copy(work, dest=None):
    work = Path(work)
    meta = json.loads((work / "export" / "render.json").read_text())
    src = Path(meta["output"])
    if not src.is_file():
        src = work / "export" / src.name
    d = check_save_dir(dest or default_save_dir(meta["videos_dir"]), meta["videos_dir"])
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, d / src.name)
    meta["saved"] = str(d / src.name)
    (work / "export" / "render.json").write_text(json.dumps(meta, indent=1))
    print(f"  saved {d / src.name}")
    return d / src.name
