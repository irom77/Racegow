"""Video discovery, ffmpeg lookup and frame access."""
import os
import shutil
import subprocess
from pathlib import Path
import cv2
from .config import VIDEO_EXTS


def list_videos(folder):
    folder = Path(folder)
    vids = sorted(p for p in folder.iterdir() if p.suffix.lower() in VIDEO_EXTS and not p.name.startswith("."))
    if not vids:
        raise SystemExit(f"No videos ({', '.join(VIDEO_EXTS)}) found in {folder}")
    return vids


def ffmpeg_exe():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise SystemExit("ffmpeg not found: install it or `pip install imageio-ffmpeg`")


def ffprobe_exe():
    return shutil.which("ffprobe")


def video_info(path):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise SystemExit(f"Cannot open {path}")
    info = dict(fps=cap.get(cv2.CAP_PROP_FPS) or 60.0, n=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
                w=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), h=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    cap.release()
    return info


def read_frames(path, start, count, step=1):
    """Yield (frame_index, BGR frame) for a contiguous range (decodes sequentially after one seek)."""
    cap = cv2.VideoCapture(str(path))
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, start))
    for k in range(count):
        ok, fr = cap.read()
        if not ok:
            break
        if k % step == 0:
            yield start + k, fr
    cap.release()


def cut_clip(src, dst, start_frame, n_frames, fps, vf=None):
    """Frame-accurate re-encode of [start_frame, start_frame + n_frames) with audio (optional video filter)."""
    cmd = [ffmpeg_exe(), "-loglevel", "error", "-y", "-ss", f"{start_frame / fps:.6f}", "-i", str(src),
           *(["-vf", vf] if vf else []), "-frames:v", str(n_frames), "-t", f"{n_frames / fps:.6f}", "-c:v", "libx264", "-preset", "fast",
           "-crf", "14", "-pix_fmt", "yuv420p", "-r", f"{fps:g}", "-c:a", "aac", "-b:a", "160k",
           "-movflags", "+faststart", str(dst)]
    subprocess.run(cmd, check=True)


def env_with_tools():
    """PATH with a usable ffmpeg directory prepended (HyperFrames shells out to ffmpeg)."""
    env = dict(os.environ)
    d = os.path.dirname(ffmpeg_exe())
    env["PATH"] = d + os.pathsep + env.get("PATH", "")
    return env
