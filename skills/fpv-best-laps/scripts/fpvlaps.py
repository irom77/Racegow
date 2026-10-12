#!/usr/bin/env python3
"""fpv-best-laps: find the fastest 3 consecutive clean laps in a folder of FPV recordings and export
the clip with a left-aligned lap-time overlay.

  python fpvlaps.py doctor
  python fpvlaps.py run      --videos DIR [--work DIR] [--track PROFILE.json] [--anchor VIDEO:FRAME]
  python fpvlaps.py extract  --videos DIR [--work DIR]
  python fpvlaps.py analyze  --videos DIR [--work DIR] [--track PROFILE.json] [--anchor VIDEO:FRAME]
  python fpvlaps.py render   --work DIR [--rank 1] [--renderer auto|hyperframes|opencv]
                             [--background blur|black] [--blur-strength 40]

`run` = extract + analyze + render. Everything is cached under the work directory, so re-running
`analyze` after a `--anchor` correction takes seconds."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def default_work(videos):
    return Path.cwd() / "fpvlaps-work" / Path(videos).resolve().name


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["doctor", "run", "extract", "analyze", "render"])
    ap.add_argument("--videos", help="folder of FPV recordings (one session per file)")
    ap.add_argument("--work", help="cache/output folder (default ./fpvlaps-work/<videos folder name>)")
    ap.add_argument("--track", help="track profile JSON to reuse (skips gate calibration)")
    ap.add_argument("--anchor", help="manual start-gate crossing VIDEO:FRAME (overrides auto calibration)")
    ap.add_argument("--workers", type=int, help="parallel videos during extraction")
    ap.add_argument("--rank", type=int, default=1, help="which result to render (1 = fastest)")
    ap.add_argument("--renderer", default="auto", choices=["auto", "hyperframes", "opencv"])
    ap.add_argument("--lead", type=float, default=1.0, help="seconds of footage before/after the 3 laps")
    ap.add_argument("--background", default="blur", choices=["blur", "black"],
                    help="fill the black side bars with a blurred copy of the footage (default) or keep them")
    ap.add_argument("--blur-strength", type=float, default=40, help="background blur radius in pixels (default 40)")
    ap.add_argument("--title", help="overlay subtitle (default: '<videos folder> · <video>')")
    a = ap.parse_args()

    if a.command == "doctor":
        from fpvlaps.doctor import doctor
        sys.exit(doctor())

    if a.command in ("run", "extract", "analyze") and not a.videos:
        ap.error("--videos is required")
    work = Path(a.work) if a.work else default_work(a.videos or ".")
    work.mkdir(parents=True, exist_ok=True)

    if a.command in ("run", "extract", "analyze"):
        from fpvlaps.media import list_videos
        from fpvlaps.extract import extract_all
        videos = list_videos(a.videos)
        print(f"[1/3] extracting features from {len(videos)} video(s) -> {work}")
        extract_all(videos, work, a.workers)
    if a.command in ("run", "analyze"):
        from fpvlaps.analyze import analyze
        print("[2/3] calibrating track + detecting laps")
        analyze(work, [v.stem for v in videos], track=a.track, anchor=a.anchor, videos_dir=a.videos)
    if a.command in ("run", "render"):
        from fpvlaps.render import render
        print("[3/3] rendering")
        render(work, rank=a.rank, renderer=a.renderer, lead=a.lead, title=a.title,
               background=a.background, blur_strength=a.blur_strength)


if __name__ == "__main__":
    main()
