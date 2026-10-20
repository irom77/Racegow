#!/usr/bin/env python3
"""fpv-best-laps: find the fastest 3 consecutive clean laps in a folder of FPV recordings and export
the clip with a left-aligned lap-time overlay.

  python fpvlaps.py doctor
  python fpvlaps.py run      --videos DIR [--work DIR] [--track PROFILE.json] [--anchor VIDEO:FRAME]
                             [--readme FILE | --no-readme] [--sectors 3 | --sectors F1,F2,...]
  python fpvlaps.py extract  --videos DIR [--work DIR]
  python fpvlaps.py analyze  --videos DIR [--work DIR] [--track PROFILE.json] [--anchor VIDEO:FRAME]
                             [--readme FILE | --no-readme]
  python fpvlaps.py verify   (--url YOUTUBE_URL | --videos DIR) [--claim 30.82 | --claim 10.27,10.33,10.22]
                             [--start h:mm:ss] [--end h:mm:ss] [--tolerance 0.05] [--track PROFILE.json]
  python fpvlaps.py save-track --work DIR [--to TRACK_DIR] [--force]
  python fpvlaps.py history  --track TRACK_DIR|NAME [--work-root DIR] [--out DIR]
  python fpvlaps.py compare  [--work DIR] [--lap [SESSION/]VIDEO:N|VIDEO@SECONDS|VIDEO:best --lap ...]
                             [--work-root DIR] [--renderer ...] [--audio a|b|none] [--no-video]
  python fpvlaps.py render   --work DIR [--rank 1] [--renderer auto|hyperframes|opencv]
                             [--background blur|black] [--blur-strength 40]
                             [--music FILE|auto] [--music-volume -10]

`run` = extract + analyze + render. Everything is cached under the work directory, so re-running
`analyze` after a `--anchor` correction takes seconds.

Track folder README: when --videos is a batch folder (e.g. Track2/2nd), README.md in that folder or
its parent is read. The reference lap is, in order: --track / --anchor, track.json next to the README,
the README's **Correct lap:** line, automatic calibration. After verifying a run, `save-track` copies
its profile next to the README for later batches. See fpvlaps/trackdir.py for the README format.

YouTube (optional, needs yt-dlp): `--url` replaces `--videos` on run/extract/analyze/verify. The video is
downloaded to <work>/source/ (default work ./fpvlaps-work/yt_<id>) and analysed as a one-video batch.
`verify` = extract + analyze + check a claimed result (`--claim`), written to <work>/verify.md. Only
analyse videos you own or have permission to use.

`history` charts best lap, best 3, median clean lap and clean-lap % over every analysed session of a
track (the result.json files under --work-root) into history.html; see fpvlaps/history.py.

`compare` renders two laps side by side with both lap clocks and the running gap (DTW alignment), plus
sector deltas, into <work>/compare/. No --lap: this session's best lap vs the best lap on the track.
See fpvlaps/compare.py."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def default_work(videos):
    return Path.cwd() / "fpvlaps-work" / Path(videos).resolve().name


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["doctor", "run", "extract", "analyze", "render", "save-track", "verify", "history",
                                        "compare"])
    ap.add_argument("--videos", help="folder of FPV recordings (one session per file)")
    ap.add_argument("--url", help="YouTube video to analyse instead of --videos (downloaded with yt-dlp)")
    ap.add_argument("--start", help="with --url: analyse from this time in the video (h:mm:ss, m:ss or seconds)")
    ap.add_argument("--end", help="with --url: analyse up to this time in the video")
    ap.add_argument("--claim", help="claimed result to verify: a 3-lap total (30.82) or the lap times "
                                    "(10.27,10.33,10.22); implies the verify step")
    ap.add_argument("--tolerance", type=float, help="verify: allowed difference per lap in seconds "
                                                    "(default 3 frames: 0.05 s at 60 fps, 0.10 s at 30 fps)")
    ap.add_argument("--work", help="cache/output folder (default ./fpvlaps-work/<videos folder name>)")
    ap.add_argument("--track", help="track profile JSON to reuse (skips gate calibration); "
                                    "history: the track folder or its name (e.g. Track2)")
    ap.add_argument("--work-root", default="fpvlaps-work",
                    help="history/compare: folder holding one work directory per session (default ./fpvlaps-work)")
    ap.add_argument("--out", help="history: folder for history.html (default: the track folder)")
    ap.add_argument("--sectors", help="sector splits: a count (split the reference lap evenly, default 3) or "
                                      "reference-lap frames F1,F2,... (saved in track.json)")
    ap.add_argument("--lap", action="append", help="compare: a lap as [SESSION/]VIDEO:N (Nth lap in laps.csv), "
                                                   "VIDEO@SECONDS or VIDEO:best; give two (default: this session's "
                                                   "best lap vs the best lap on the track)")
    ap.add_argument("--audio", default="a", choices=["a", "b", "none"],
                    help="compare: audio of lap A (default), lap B, or none")
    ap.add_argument("--no-video", action="store_true", help="compare: only compare.md/json and gap.png")
    ap.add_argument("--anchor", help="manual start-gate crossing VIDEO:FRAME (overrides auto calibration)")
    ap.add_argument("--readme", help="track README to use (default: README.md in --videos or its parent)")
    ap.add_argument("--no-readme", action="store_true", help="ignore the track README")
    ap.add_argument("--to", help="save-track: folder to save track.json/.npz in (default: the track README's folder)")
    ap.add_argument("--force", action="store_true", help="save-track: replace an existing track.json (kept as .bak)")
    ap.add_argument("--workers", type=int, help="parallel videos during extraction")
    ap.add_argument("--rank", type=int, default=1, help="which result to render (1 = fastest)")
    ap.add_argument("--renderer", default="auto", choices=["auto", "hyperframes", "opencv"])
    ap.add_argument("--lead", type=float, default=1.0, help="seconds of footage before/after the 3 laps "
                                                                     "(compare: before/after the laps)")
    ap.add_argument("--background", default="blur", choices=["blur", "black"],
                    help="fill the black side bars with a blurred copy of the footage (default) or keep them")
    ap.add_argument("--blur-strength", type=float, default=40, help="background blur radius in pixels (default 40)")
    ap.add_argument("--music", help="mix music under the clip: an audio file, or 'auto' for a generated track "
                                    "(default: no music, original audio only)")
    ap.add_argument("--music-volume", type=float, default=-10.0,
                    help="with --music: music level relative to the motor audio, in dB (default -10)")
    ap.add_argument("--title", help="overlay subtitle (default: '<videos folder> · <video>')")
    a = ap.parse_args()

    if a.command == "doctor":
        from fpvlaps.doctor import doctor
        sys.exit(doctor())

    if a.command == "save-track":
        from fpvlaps.trackdir import save_track
        if not a.work:
            ap.error("--work is required")
        save_track(a.work, a.to, a.force)
        return

    if a.command == "history":
        from fpvlaps.history import write_history
        if not a.track:
            ap.error("--track is required (track folder or name)")
        write_history(a.track, a.work_root, a.out)
        return

    if a.command == "compare":
        from fpvlaps.compare import compare
        compare(a.work, a.lap, a.work_root, a.renderer, a.audio, a.lead, not a.no_video)
        return

    needs_input = a.command in ("run", "extract", "analyze", "verify")
    if needs_input and bool(a.videos) == bool(a.url):
        ap.error("give either --videos or --url")
    if (a.start or a.end) and not a.url:
        ap.error("--start/--end need --url (cut local recordings yourself)")
    if a.url:
        from fpvlaps.youtube import default_work as yt_work
        work = Path(a.work) if a.work else yt_work(a.url)
    else:
        work = Path(a.work) if a.work else default_work(a.videos or ".")
    work.mkdir(parents=True, exist_ok=True)

    if a.url and needs_input:
        from fpvlaps.youtube import prepare
        print(f"[0/3] downloading {a.url} -> {work / 'source'}")
        print("  only analyse videos you own or have permission to use (YouTube terms of service)")
        a.videos = str(prepare(a.url, work, a.start, a.end)[0])
    if needs_input:
        from fpvlaps.media import list_videos
        from fpvlaps.extract import extract_all
        videos = list_videos(a.videos)
        print(f"[1/3] extracting features from {len(videos)} video(s) -> {work}")
        extract_all(videos, work, a.workers)
    if a.command in ("run", "analyze", "verify"):
        from fpvlaps.analyze import analyze
        from fpvlaps.trackdir import choose_reference
        print("[2/3] calibrating track + detecting laps")
        ch = choose_reference(a.videos, a.track, a.anchor, a.readme, not a.no_readme)
        if ch["readme"]:
            print(f"  track README: {ch['readme']}")
        print(f"  reference: {ch['how']}")
        try:
            analyze(work, [v.stem for v in videos], track=ch["track"], anchor=ch["anchor"], videos_dir=a.videos,
                    correct_lap=ch["correct_lap"], readme=ch, sectors=a.sectors)
        except RuntimeError as e:
            if a.command != "verify":
                raise
            from fpvlaps.verify import cannot_time
            cannot_time(work, a.claim, e)
            sys.exit(1)
    if a.command == "verify" or (a.claim and a.command in ("run", "analyze")):
        from fpvlaps.verify import verify
        print("[verify] checking the claim" if a.claim else "[verify] no --claim: reporting the best clean laps")
        verify(work, a.claim, a.tolerance)
    if a.command in ("run", "render"):
        from fpvlaps.render import render
        print("[3/3] rendering")
        render(work, rank=a.rank, renderer=a.renderer, lead=a.lead, title=a.title,
               background=a.background, blur_strength=a.blur_strength, music=a.music,
               music_volume=a.music_volume)


if __name__ == "__main__":
    main()
