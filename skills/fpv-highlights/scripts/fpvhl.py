#!/usr/bin/env python3
"""fpv-highlights: cut the most interesting moments of a folder of FPV recordings (freestyle, cruising,
park sessions; not racing) into one short, by default a vertical YouTube Short of at most 60 s.

  python fpvhl.py run     --videos DIR [--work DIR] [--length 60] [--layout fit|crop|wide] [--save-to DIR]
  python fpvhl.py scan    --videos DIR [--work DIR] [--workers N]
  python fpvhl.py pick    --videos DIR [--work DIR] [--length 60] [--clip 5] [--per-video 2] [--per-scene 2]
                          [--exclude VIDEO[:A-B],...] [--include VIDEO:A-B,...]
  python fpvhl.py render  --work DIR [--layout fit|crop|wide] [--title TEXT] [--music FILE|auto]
                          [--save-to DIR | --no-save]
  python fpvhl.py save    --work DIR [--save-to DIR]
  python fpvhl.py meta    --work DIR [--title TEXT] [--quad NAME] [--pilot PAPFPV] [--place TEXT]
  python fpvhl.py upload  --work DIR [--privacy public|unlisted|private] [--expect-channel @niuk9290]
                          [--playlist "FPV highlights" | --no-playlist]
  python fpvhl.py playlist [--work DIR] [--video ID|URL ...] [--playlist "FPV highlights"]

`run` = scan + pick + render. Scans are cached in <work>/scan/, so `pick` with other options or
overrides takes seconds. Times (A-B) are seconds in the recording, as in picks.md.

The finished short is copied to <recordings parent>/fpv-shorts/<recordings folder>/ (never inside the
recordings folder, which is deleted by hand after the short is published and reviewed). `--save-to`
picks another folder, `--no-save` skips the copy."""
import argparse
import os
import sys
from pathlib import Path

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")      # forked workers + threaded BLAS hang (see fpv-best-laps)
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["run", "scan", "pick", "render", "save", "meta", "upload", "playlist"])
    ap.add_argument("--videos", help="folder of recordings")
    ap.add_argument("--work", help="cache/output folder (default ./fpvlaps-work/hl_<videos folder name>)")
    ap.add_argument("--workers", type=int, help="parallel videos while scanning")
    ap.add_argument("--length", type=float, default=60, help="maximum length of the short in seconds (default 60)")
    ap.add_argument("--clip", type=float, default=5, help="typical clip length in seconds (default 5; clips grow "
                                                          "to at most 1.6x this while the action lasts)")
    ap.add_argument("--per-video", type=int, default=2, help="at most this many clips from one recording")
    ap.add_argument("--per-scene", type=int, default=2, help="at most this many clips from one place (recordings "
                                                              "that look alike), raised only if --length can't be filled")
    ap.add_argument("--exclude", help="leave out recordings or parts: VIDEO or VIDEO:A-B, comma separated")
    ap.add_argument("--include", help="force clips in: VIDEO:A-B, comma separated (seconds in the recording)")
    ap.add_argument("--order", default="hook", choices=["hook", "time", "score"],
                    help="hook = best clip first, then recording order (default)")
    ap.add_argument("--layout", default="fit", choices=["fit", "crop", "wide"],
                    help="fit = vertical 1080x1920, whole picture over a blurred fill (default); crop = vertical, "
                         "picture cropped to fill; wide = 1920x1080 landscape")
    ap.add_argument("--title", help="render: text in the top band (fit layout); meta: YouTube title")
    ap.add_argument("--music", help="mix music under the clips: an audio file or 'auto' (default: original audio)")
    ap.add_argument("--music-volume", type=float, default=-10.0)
    ap.add_argument("--save-to", help="where to copy the finished short (default <recordings parent>/fpv-shorts/<folder>)")
    ap.add_argument("--no-save", action="store_true", help="don't copy the short out of the work folder")
    ap.add_argument("--pilot", default="PAPFPV")
    ap.add_argument("--quad", help="meta: quad(s) flown, for the description")
    ap.add_argument("--place", help="meta: where it was flown")
    ap.add_argument("--date", help="meta: date flown YYYY-MM-DD, or 'none' when the folder holds several sessions "
                                   "(default: from the folder name, else file dates)")
    ap.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    ap.add_argument("--expect-channel", default="@niuk9290")
    ap.add_argument("--playlist", default="FPV highlights",
                    help="upload/playlist: YouTube playlist the short goes in (created if missing)")
    ap.add_argument("--no-playlist", action="store_true", help="upload: don't add it to a playlist")
    ap.add_argument("--video", action="append", default=[], help="playlist: also add this video id/URL")
    ap.add_argument("--again", action="store_true", help="upload: even if this short was uploaded before")
    a = ap.parse_args()

    if a.command in ("run", "scan", "pick") and not a.videos:
        ap.error("--videos is required")
    work = Path(a.work) if a.work else Path.cwd() / "fpvlaps-work" / f"hl_{Path(a.videos or '.').resolve().name}"
    if a.command == "playlist":
        from fpvhl.youtube import playlist
        try:
            playlist(a.work, a.video, a.playlist)
        except PermissionError as e:
            raise SystemExit(str(e))
        return
    if a.command in ("render", "save", "meta", "upload") and not (work / "picks.json").exists():
        ap.error(f"no picks in {work}: run `pick` (or `run`) first, or pass --work")
    work.mkdir(parents=True, exist_ok=True)

    if a.command in ("run", "scan", "pick"):
        from fpvhl.scan import list_videos, scan_all
        vids = list_videos(a.videos)
        print(f"[1/3] scanning {len(vids)} recording(s) -> {work}")
        good = scan_all(vids, work, a.workers)
        print(f"  {len(good)} usable, {len(vids) - len(good)} skipped (unreadable or under 2 s)")
        if a.command == "scan":
            return
        from fpvhl.pick import pick
        print("[2/3] picking clips")
        pick(work, good, a.videos, length=a.length, clip=a.clip, per_video=a.per_video,
             exclude=a.exclude, include=a.include, order=a.order, per_scene=a.per_scene)
    if a.command in ("run", "render"):
        from fpvhl.render import render
        print("[3/3] rendering")
        render(work, layout=a.layout, title=a.title, music=a.music, music_volume=a.music_volume,
               save_to=None if a.no_save else (a.save_to or "default"))
    if a.command == "save":
        from fpvhl.render import save_copy
        save_copy(work, a.save_to)
    if a.command == "meta":
        from fpvhl.youtube import build_meta
        build_meta(work, title=a.title, quad=a.quad, pilot=a.pilot, place=a.place, date=a.date)
    if a.command == "upload":
        from fpvhl.youtube import upload
        upload(work, a.privacy, a.expect_channel, a.again, None if a.no_playlist else a.playlist)


if __name__ == "__main__":
    main()
