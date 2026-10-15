"""YouTube input: download a video with yt-dlp into <work>/source/ and turn it into a one-video batch.

    <work>/source/
      raw/<id>.mp4        the download as YouTube serves it (highest frame rate, then resolution)
      youtube/<id>.mp4    what gets analysed: the raw file, or a constant-frame-rate re-encode when
                          the download has a variable frame rate or --start/--end pick a section
      source.json         URL, id, title, uploader, frame rate, and the section offset

Only analyse videos you own or have permission to use (YouTube's terms of service)."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from .media import ffmpeg_exe, ffprobe_exe
from .trackdir import parse_clock

ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
BATCH = "youtube"


def video_id(url):
    """The 11-character video id of a youtube.com / youtu.be / shorts / embed URL (or a bare id)."""
    if ID_RE.match(url):
        return url
    u = urlparse(url if "//" in url else "https://" + url)
    host = (u.hostname or "").lower()
    cand = None
    if host.endswith("youtu.be"):
        cand = u.path.strip("/").split("/")[0]
    elif "youtube" in host:
        if u.path == "/watch":
            cand = (parse_qs(u.query).get("v") or [None])[0]
        else:
            parts = u.path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] in ("shorts", "embed", "live", "v"):
                cand = parts[1]
    if not cand or not ID_RE.match(cand):
        raise SystemExit(f"Not a YouTube video URL: {url}")
    return cand


def link(vid, seconds):
    """Link that opens the video a moment before `seconds` (YouTube's t= takes whole seconds)."""
    return f"https://youtu.be/{vid}?t={max(0, int(seconds) - 1)}"


def default_work(url):
    return Path.cwd() / "fpvlaps-work" / f"yt_{video_id(url)}"


def ytdlp_cmd():
    """yt-dlp from this Python environment (`pip install yt-dlp`), else the one on PATH."""
    try:
        import yt_dlp  # noqa: F401
        return [sys.executable, "-m", "yt_dlp"]
    except ImportError:
        exe = shutil.which("yt-dlp")
        if exe:
            return [exe]
    raise SystemExit("yt-dlp not found: pip install yt-dlp (or install it on PATH)")


def js_runtime_args():
    """YouTube extraction needs a JavaScript runtime; yt-dlp only looks for deno by default."""
    if shutil.which("deno"):
        return []
    node = shutil.which("node")
    return ["--js-runtimes", f"node:{node}"] if node else []


def download(url, raw_dir, log=print):
    """Download into raw_dir/<id>.mp4 (cached): highest frame rate first, then resolution, preferring
    H.264 (frame-accurate seeking in OpenCV). Returns (path, info dict)."""
    vid = video_id(url)
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    out, info_p = raw_dir / f"{vid}.mp4", raw_dir / f"{vid}.info.json"
    if out.is_file() and info_p.is_file():
        log(f"  [download] {vid}: cached")
        return out, json.loads(info_p.read_text())
    cmd = ytdlp_cmd() + js_runtime_args() + [
        "--no-playlist", "--no-progress", "-S", "fps,res,vcodec:h264,acodec:m4a",
        "--merge-output-format", "mp4", "--ffmpeg-location", ffmpeg_exe(),
        "-o", str(raw_dir / "%(id)s.%(ext)s"),
        "--print-to-file", "%(.{id,title,uploader,channel,upload_date,duration,fps,width,height,format_id,"
                           "webpage_url})j", str(info_p),
        f"https://www.youtube.com/watch?v={vid}"]
    log(f"  [download] {vid}: yt-dlp (highest frame rate, original resolution)")
    r = subprocess.run(cmd)
    if r.returncode or not out.is_file():
        info_p.unlink(missing_ok=True)
        raise SystemExit(f"yt-dlp could not download {url} (exit {r.returncode})")
    info = json.loads(info_p.read_text().strip().splitlines()[-1])
    info_p.write_text(json.dumps(info, indent=1))
    return out, info


def probe_rates(path):
    """(r_frame_rate, avg_frame_rate) of the first video stream as floats; None without ffprobe."""
    exe = ffprobe_exe()
    if not exe:
        return None
    r = subprocess.run([exe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=r_frame_rate,avg_frame_rate", "-of", "json", str(path)],
                       capture_output=True, text=True)
    try:
        s = json.loads(r.stdout)["streams"][0]
    except (ValueError, KeyError, IndexError):
        return None

    def f(x):
        a, _, b = x.partition("/")
        return float(a) / float(b or 1) if float(b or 1) else 0.0
    return f(s["r_frame_rate"]), f(s["avg_frame_rate"])


def nominal_fps(info, rates):
    """The frame rate to analyse at: YouTube's stated rate, else the stream's."""
    if info.get("fps"):
        return float(info["fps"])
    if rates and rates[0]:
        return rates[0]
    return 60.0


def is_vfr(rates):
    return bool(rates and rates[0] and rates[1] and abs(rates[0] - rates[1]) / rates[0] > 0.002)


def normalise(src, dst, fps, start=None, end=None, blend=False):
    """Constant-frame-rate re-encode at `fps`, optionally only start..end seconds. Accurate seek,
    near-lossless, keeps the audio. Frames are placed on their real timestamps (duplicated or dropped
    as needed); with `blend`, added frames are blends of their neighbours instead of copies, so the
    frame-to-frame motion the crash/flight checks rely on stays realistic."""
    vf = f"fps={fps:g}" if not blend else f"fps={fps / 2:g},framerate=fps={fps:g}"
    cmd = [ffmpeg_exe(), "-loglevel", "error", "-y"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    if end:
        cmd += ["-to", f"{end:.3f}"]
    cmd += ["-i", str(src), "-vf", vf, "-c:v", "libx264", "-preset", "fast", "-crf", "14",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(dst)]
    subprocess.run(cmd, check=True)


def analysis_fps(fps):
    """Frame rate to analyse at. Below 50 fps it is doubled (30 -> 60) with blended in-between frames: lap matching steps
    through the video in frames, so a 30 fps video against a profile made from 60 fps footage would
    look like a lap flown at twice the speed, at the edge of what the matcher allows."""
    return fps * 2 if fps < 50 else fps


def prepare(url, work, start=None, end=None, log=print):
    """Download `url` and lay it out as a one-video batch folder. Returns (batch folder, source dict)."""
    raw, info = download(url, Path(work) / "source" / "raw", log)
    return layout(raw, dict(info, url=url, id=info.get("id") or video_id(url)), work, start, end, log)


def layout(raw, info, work, start=None, end=None, log=print):
    """<work>/source/youtube/<name>.mp4 from a downloaded file: the file itself, or a constant-frame-rate
    re-encode for a variable frame rate, a frame rate below 50 fps, or a --start/--end section ('h:mm:ss',
    'm:ss' or seconds). Saves <work>/source/source.json."""
    src_dir = Path(work) / "source"
    vid = info["id"]
    t0 = parse_clock(start) if start else 0.0
    t1 = parse_clock(end) if end else None
    if t1 is not None and t1 <= t0:
        raise SystemExit(f"--end {end} must be after --start {start or 0}")
    rates = probe_rates(raw)
    fps = nominal_fps(info, rates)
    afps = analysis_fps(fps)
    vfr = is_vfr(rates)
    batch = src_dir / BATCH
    batch.mkdir(parents=True, exist_ok=True)
    name = vid + (f"_{int(t0)}-{int(t1) if t1 is not None else 'end'}" if start or end else "")
    out = batch / f"{name}.mp4"
    for old in batch.iterdir():                  # one video per batch: the section asked for this time
        if old != out:
            old.unlink()
    if not out.exists():
        why = [w for w in ("variable frame rate" if vfr else "",
                           f"{fps:g} fps doubled to {afps:g}" if afps != fps else "",
                           f"section {start or '0'}-{end or 'end'}" if start or end else "") if w]
        if why:
            log(f"  [normalise] {', '.join(why)}: re-encoding at a constant {afps:g} fps")
            normalise(raw, out, afps, t0, t1, blend=afps != fps)
        else:
            try:
                out.hardlink_to(raw)
            except OSError:
                shutil.copy2(raw, out)
    src = dict(url=info["url"], id=vid, title=info.get("title"), uploader=info.get("uploader") or info.get("channel"),
               upload_date=info.get("upload_date"), duration=info.get("duration"), fps=fps, analysis_fps=afps,
               width=info.get("width"), height=info.get("height"), format_id=info.get("format_id"),
               variable_frame_rate=vfr, offset_s=t0, end_s=t1, raw=str(raw), video=str(out), name=name)
    (src_dir / "source.json").write_text(json.dumps(src, indent=1))
    if fps < 50:
        log(f"  note: {fps:g} fps upload: crossings are timed to +-{3 / fps:.2f}s instead of +-0.05s")
    return batch, src


def load_source(work):
    p = Path(work) / "source" / "source.json"
    return json.loads(p.read_text()) if p.is_file() else None
