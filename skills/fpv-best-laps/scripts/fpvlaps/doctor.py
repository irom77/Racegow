"""Environment check: prints what is available and the exact commands to fix what is not."""
import shutil
import sys


def doctor():
    ok = True
    print(f"python   {sys.version.split()[0]}")
    for mod, pip in (("cv2", "opencv-python-headless"), ("numpy", "numpy")):
        try:
            m = __import__(mod)
            print(f"{mod:8} {getattr(m, '__version__', 'ok')}")
        except ImportError:
            ok = False
            print(f"{mod:8} MISSING  -> pip install {pip}")
    ff = shutil.which("ffmpeg")
    if not ff:
        try:
            import imageio_ffmpeg
            ff = imageio_ffmpeg.get_ffmpeg_exe() + " (imageio-ffmpeg)"
        except Exception:
            pass
    print(f"ffmpeg   {ff or 'MISSING  -> install ffmpeg or pip install imageio-ffmpeg'}")
    ok = ok and bool(ff)
    probe, npx = shutil.which("ffprobe"), shutil.which("npx")
    hf = bool(probe and npx and shutil.which("ffmpeg"))
    print(f"ffprobe  {probe or 'missing (only needed for the HyperFrames renderer)'}")
    print(f"npx      {npx or 'missing (only needed for the HyperFrames renderer)'}")
    print(f"renderer {'hyperframes' if hf else 'opencv (fallback)'}")
    if npx and not hf:
        print("         HyperFrames needs ffmpeg AND ffprobe on PATH (a static ffmpeg build provides both)")
    try:
        import yt_dlp
        yt = f"{yt_dlp.version.__version__} (python module)"
    except ImportError:
        yt = shutil.which("yt-dlp")
    print(f"yt-dlp   {yt or 'missing (only needed for --url / verify from YouTube) -> pip install yt-dlp'}")
    if yt and not (shutil.which("deno") or npx):
        print("         YouTube needs a JavaScript runtime for yt-dlp: install Node.js or deno")
    if yt:
        try:
            import yt_dlp_ejs  # noqa: F401
        except ImportError:
            print("         yt-dlp-ejs missing: YouTube may offer no video formats -> pip install 'yt-dlp[default]'")
    print("status   " + ("ready" if ok else "NOT READY"))
    return 0 if ok else 1
