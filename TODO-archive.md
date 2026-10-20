# TODO archive

Completed items moved out of [TODO.md](TODO.md), kept for the decisions and test notes. Open follow-ups from these features stay in TODO.md.

## Feature: side-by-side lap comparison (done)

Inspired by FPV DVR Lap Timer's "Compare two laps".

- [x] `compare --lap SPEC --lap SPEC` (`compare.py`): a lap is `[SESSION/]VIDEO:N` (Nth lap of the
  video, laps.csv order), `VIDEO@SECONDS` (lap starting nearest that time, the way report.md names
  laps) or `VIDEO:best`. SESSION = a work directory or its name under `--work-root`; without it,
  `--work`, else the one session that has a video of that name (ambiguous names are an error).
- [x] Running gap: lap B's 20 Hz descriptors aligned to lap A's with the fixed-endpoint DTW from
  sectors.py; gap = A frame - B frame at each point, smoothed 0.5 s, pinned to 0 at the gate and to
  the lap-time difference at the finish. `compare.md`: furthest behind / ahead, where A loses and
  gains most (1.5 s windows, with the sector), sector deltas with the gap after each sector.
- [x] Sector deltas: both laps' own sector splits when they share a reference lap (match report.md
  exactly), else lap A's (or lap B's mapped across), else an even split of lap A. Lap B's point at
  each boundary snapped at 60 fps (±15 frames) and the curve bent through it.
- [x] Default pair (no `--lap`): best clean lap of `--work` vs the best clean lap of every session
  `history` collects for that track (track = README folder, else the batch folder's parent); the next
  fastest when this session holds the record.
- [x] Video, 1920x1080: label band (session, video, lap N, why picked), both laps cropped to the
  picture side by side (A blue / B orange tags), lap clocks from each lap's own gate frame (gold when
  finished), gap chart below with the sign-coloured area, a cursor at lap A's position and sector
  deltas revealed as A passes each boundary. HyperFrames (`assets/compare/index.html`, audio flags set
  in the static HTML, 1 s keyframes in the cut clips) and OpenCV. `auto` = OpenCV for compare: 41 s
  vs 14.8 min for HyperFrames on the 15.8 s Track 2 clip. `--audio a|b|none`, `--no-video`.
- Tested on Track 2: 2nd's best lap (13.50 s) vs 1st's best (13.73 s): A loses up to 0.30 s in S1 and
  takes 0.5 s back in S2, finishing 0.23 s ahead. Pairwise sector times vs each lap's own splits
  (same session): 0.05 s mean difference. `tests/test_compare.py` (synthetic laps with known
  per-sector speeds, lap specs, default pair).

## Feature: sector splits and theoretical best (done)

- [x] `--sectors N` (2-10, split the reference lap evenly; default 3, `SECTORS_DEFAULT`) or
  `--sectors F1,F2,...` (reference-video frames, strictly inside the reference lap). Frames are saved
  as `sectors` in the track profile: `<work>/track.json`, or the `--track` / track-folder
  `track.json` when one is reused, so later batches split the same way.
- [x] Mapping (`sectors.py`): fixed-endpoint DTW of each clean lap against the reference lap at 20 Hz,
  steps (1,1), (1,2), (2,1), with backpointers; a boundary goes to the mean lap step aligned to its
  reference step. Then snapped to the exact frame (±9 frames, `SECTOR_REFINE_SEARCH`) against a
  consensus ±0.5 s window from the ~40 best-matching clean laps (`refine` got a `search` argument).
  Proportional fallback when the length ratio is outside 0.5-2x; laps whose boundaries come out of
  order get no sectors.
- [x] `result.json`: `sectors` (count, boundaries, source, best, best_lap, median, theoretical_best,
  best_real_lap) and per lap `sectors` (seconds) + `sector_frames`. `report.md`: sector table of the
  10 fastest clean laps plus the best-3 laps (★), best per sector in bold, median and best-sector
  rows, theoretical best vs best lap, where each best sector came from, and the sector where the
  best-3 laps lose most time. `sheets/sectors.jpg`: the reference view at each boundary.
- Tested on Track 2 batch 2nd: 48/48 clean laps timed; theoretical best 12.83 s (3 even sectors) /
  12.88 s (4 sectors at 3700, 3950, 4150) vs best lap 13.50 s. A sheet of the mapped boundaries of the
  6 fastest laps showed the same view as the reference in every row. `tests/test_sectors.py`
  (synthetic laps with known per-sector speeds).

## Feature: progress across sessions and consistency stats (done)

Inspired by FPV DVR Lap Timer's progress and consistency charts. No database: reads the saved
`result.json` files.

- [x] `history --track TRACK_DIR|NAME` (`history.py`): sessions = `<work-root>/*/result.json`
  (default `./fpvlaps-work`; nested folders such as old experiments are skipped). A session belongs to
  the track when its batch folder, track README or profile is inside the track folder, or a folder in
  its path is named after the track (`Track2`, `Track2-1st`, not `Track20`): older result.json files
  have no `track_readme`, and some batches were analysed through a symlink folder. The same footage
  analysed twice (same video names + durations) counts once, newest run kept.
- [x] Session date: `YYYY-MM-DD` in the batch folder name, else the median file date of the
  recordings (HDZero has no clock but the SD card copy keeps the file times; dates before 2015
  ignored), else the first analysis.
- [x] `history.html`: self-contained, inline SVG small multiples (lap time: best + median clean lap;
  best 3; clean-lap %), one point per session evenly spaced, hover titles, a table view, light and
  dark mode. Plus `history.json`. Written to the track folder by default (`--out`), and linked from
  every session's `report.md` between `<!-- history -->` markers (refreshed in place).
- [x] `report.md` **Consistency** table: clean laps, std dev and median of clean laps, best to median
  gap, bad-lap rate (every rejected lap) and crashes (laps disarmed or stopped before the finish).
- Tested on Track 1 (Air65_2) and Track 2 (1st, 2nd); `tests/test_history.py`.

## Feature: verify a run from a YouTube URL (done)

Let a pilot (or race organiser) point the tool at a YouTube video and get the 3-lap time and lap
splits verified, e.g. to check a leaderboard submission. Optional: nothing changes without `--url`,
`--claim` or the `verify` command.

- [x] `--url` on `run`/`extract`/`analyze` and a `verify` command, instead of `--videos`. `youtube.py`
  downloads with `yt-dlp` (`-S fps,res,vcodec:h264`, so the highest frame rate, then the original
  resolution) into `<work>/source/raw/`, and lays it out as a one-video batch in `source/youtube/`.
  yt-dlp now needs a JavaScript runtime for YouTube: node is passed with `--js-runtimes` when deno
  is missing. Default work dir `fpvlaps-work/yt_<id>`.
- [x] `--claim 30.82` or `--claim 10.27,10.33,10.22`; tolerance ±3 frames per lap, at least 0.05 s
  (0.10 s at 30 fps), `--tolerance` overrides. Every chain of 3 laps (clean or not) is compared, so
  `verify.md` can say *why* matching laps don't count.
- [x] `--start`/`--end`: the section is re-encoded at a constant frame rate; the offset is kept so
  every crossing links to the right second.
- [x] Upload differences. VFR: re-encoded at a constant rate. 30 fps: doubled to 60 with blended
  frames (plain duplicates zeroed every other frame's motion, which broke the flight mask and the
  lap period). Compression/overlay: the uploaded Track 2 clip matched the profile at cost 0.47-0.51
  vs 0.25-0.27 for the same laps in the raw file; a lap rejected *only* for cost counts with a caveat
  when the whole video's median cost is above the clean limit and the lap is within 1.25x of it.
  Edits: OSD timer offset fitting (`floor(t + c) = s`), a jump must show on every readable timer
  (Betaflight crash-flip mode swaps the on-time timer into the fly-timer slot: two false "cuts" in
  23 raw recordings before this rule, none after).
- [x] `verify.md` / `verify.json`: verdict (verified / mismatch / not verifiable / detected), detected
  vs claimed laps, `sheets/verify_crossings.jpg`, `https://youtu.be/<id>?t=` per crossing, edits.
  When the analysis can't run (no parked start, no reference), `verify` still writes a
  not-verifiable report with the fix.
- [x] `--readme`/`--track` as the reference for uploads; self-calibration is marked less certain.
  Core change: with a profile, a session period above 1.5x the profile's is treated as a two-lap
  alias (short clips); Track2/2nd re-analysis is identical before and after.
- [x] Docs: SKILL.md section, README (usage, options, verdicts, module map, outputs, limits),
  method.md, `yt-dlp` in requirements and `doctor`, YouTube terms-of-service note.
- [x] After testing other pilots' uploads (RealSco 33.70 s, Whooperza 43.20 s, both Track 2):
  - the verdict uses the claimed **total** (±3 frames); claimed lap times are shown against ±0.15 s
    only. Whooperza's own lap timer ticked 4-10 frames after the tool's crossings: splits
    -0.08/+0.11/-0.05 s, total -0.03 s.
  - a track profile is valid only for the same build (each pilot builds the track at home). Wrong
    room can't be detected: RealSco's room scored *higher* against the user's Track 2 profile than the
    user's own upload. Docs say: other pilots' videos get `--no-readme --anchor`.
  - anchors for uploads: from the clip's lap-timer overlay (clock reading -> frame where it read 0)
    or the gate pass in the opening seconds (SKILL.md).
  - OSD: wider character pitch (34-44 px, seen 40 px) tried only when the default layout finds no
    timer, and only accepted when it trends like a clock (link quality `28:100` also reads as mm:ss).
    Used by verify only (edits; overruling motion-guessed disarms at clip edges), not arm detection.
    The clock fit takes a majority vote over ±1 s first, so 1-in-4 misreads don't split it.
  - yt-dlp needs `yt-dlp[default]` (yt-dlp-ejs): plain yt-dlp got only storyboard images for
    RealSco's "made for kids" video.
- Tested: https://youtu.be/GG7-ezzppak (own Track 2 clip, claim 13.85/13.85/13.73) verified at 60 fps,
  as a 30 fps copy and with `--start/--end`; a wrong claim gives a mismatch; a copy with 5 s cut out of
  lap 2 reports the edit at 0:20.00 (+4.98 s); without a reference: not verifiable with the fix.
  Unit tests: `tests/test_verify.py`.
- Other pilots (both `--no-readme --anchor`): Whooperza https://youtu.be/Whlfubf2QkM (43.20 s,
  anchor 250 from its own lap-timer overlay) verified at 43.17 s. RealSco
  https://youtu.be/wqoGGwFT4bo (33.70 s) stays a **mismatch**: 11.33/11.00/11.25 = 33.58 s with
  the anchor at frame 186 (34.02 s at 160). The quad is parked only ~2.5 s and the gate pass
  spans ~156-190, so the start line can't be pinned to better than ~0.1 s by hand. No OSD edits.
- Wide-layout OSD search vs HEAD: timer location and picture box identical on all 58 readable
  Track 1/Track 2 recordings, incl. Track2/2nd hdz_0016/0017 (no default timer, so the wide search
  ran and correctly found nothing). Track2/1st hdz_0014/0024 are truncated (no moov atom).

## Remove hard-coded local paths (done)

- [x] Moved the original prototype from `src/` to `legacy/` with a README pointing to the skill.
- [x] Replaced the local folders in `legacy/extract.py` and `legacy/analyze.py` with placeholders
  (`/path/to/videos`, relative `work/...`). The old paths remain in earlier commits.
- [x] `skills/fpv-best-laps/evals/evals.json`: test prompt now uses `/path/to/videos`.
- Decided: keep git history as is (no `git filter-repo`). The old paths are only folder names, and
  rewriting would change every commit hash and force existing clones to re-clone.

## Feature: blurred background in the exported clip (done)

HDZero (and other 4:3) footage sits in a 16:9 frame with black bars on the sides, and the lap panel
sits on top of the picture. Fill that space with a blurred, darkened copy of the footage so the clip
looks finished and the overlay reads better.

- Decided: blur the **side bars only** (a blurred, scaled-up, darkened copy of the footage behind the
  sharp 4:3 picture). It is the simplest and fastest to render in both renderers; the lap panel stays
  as it is. A frosted backdrop behind the panel can come later if wanted.
- [x] Detect the active picture area per video (`active_area`: brightest value per column/row over
  ~24 frames; HDZero gives x 160..1119 of 1280x720).
- [x] Both renderers: done once in the ffmpeg cut (`blur_filter`: scale to cover, blur at quarter
  resolution, dim to 60%, sharp picture on top). Simpler than separate CSS and OpenCV layers, and
  identical in both; `assets/overlay/index.html` is unchanged.
- [x] Option `--background blur|black` (default `blur`), `--blur-strength` (default 40 px).
- [x] Update the skill: SKILL.md render step, README options table and rendering section,
  method.md, and refresh `docs/overlay-final.jpg`.
- [x] Test-render with `--renderer opencv`: Track 2 41.43 s clip, blurred bars identical to
  HyperFrames, 2607 frames, audio kept, 3 min (HyperFrames: ~10 min).
- Decided: clips already on YouTube keep their black bars (no re-upload); new clips get the blur.

## Feature: background music in the exported clip (done)

The raw clip only has motor noise. A music bed makes it shareable. Keep it simple.

- [x] Option `--music <file>` to mix a track under the clip, and `--music auto` for a random track.
  Instead of bundling downloaded tracks (licence checks in a public repo), `auto` generates one with
  numpy (`music.py`: kick, clap, hats, off-beat bass, arpeggio with delay; random tempo 128-144 bpm,
  minor key, chords and patterns; the seed is saved in `render_rankN.json`).
- [x] Mix: music looped/trimmed to the clip length, 1 s fade in, 1.5 s fade out. Both music and motor
  audio levelled to -16 LUFS, then the music placed under the motor with `--music-volume` (default
  -10 dB, chosen by ear on the Track 2 clip; the first try, motor 12 dB under the music, drowned the
  motor). One `ffmpeg` pass after either renderer, video stream copied (a few seconds).
- Decided: **off by default** (no music, original audio kept, e.g. for race-verification clips).
  The mix above is applied only when music is asked for (`--music`).
- [x] Docs: SKILL.md render step, README options table and rendering section, method.md.
- Moved to TODO.md (follow-ups): `--music-seed N`.

## Feature: read the track folder README automatically (done)

Each track folder (e.g. `RaceeGow6/Track2/`) has a `README.md` with the organiser's demo video, the
time its flythrough starts, and one lap the pilot knows is correct. Batches live in subfolders
(`Track2/1st`, `Track2/2nd`, ...). The tool picks all of that up, so timing a new batch is just
`fpvlaps.py run --videos Track2/2nd` with no flags. Code: `scripts/fpvlaps/trackdir.py`.

- [x] README format: the bold labels the YouTube skill already reads, `**Demo video:** <url> ("title")`
  and `**Flythrough starts at:** 1:00`, plus `**Correct lap:** 1st/hdz_0022 at 0:59` (or
  `frame 3539`; video path relative to the track folder). Template:
  `assets/track-README-template.md`.
- [x] `README.md` is looked up in `--videos` and its parent. Reference, in order: `--track`/`--anchor`,
  `track.json` next to the README, the README's correct lap, automatic calibration.
  `--readme FILE` / `--no-readme` override. The correct lap's time is used as given (nearest frame),
  not snapped: tried snapping to the parked start view, but it moved an exact crossing 0.38 s early and
  shifted every crossing with it, and a consistent line times laps equally well wherever it is.
- [x] The correct lap may be in another batch folder: that one video is extracted on its own into
  `<work>/reference/<folder>/` and named by its README path (`1st/hdz_0022`).
- [x] `save-track --work W [--to DIR] [--force]` copies a verified run's profile next to the README.
  It won't replace an existing `track.json` without `--force` (old one kept as `.bak`), and refuses
  runs that only reused a profile.
- [x] `report.md` has a "Reference to check against" block: README path, demo link opening at the
  flythrough, and where the reference lap came from.
- [x] Docs: SKILL.md, skill README (track folder layout, options), template track README.
- [x] Also: `list_videos` skips the tool's own `best3_laps_*` clips kept next to the footage.

## New skills: YouTube upload and RaceGOW leaderboard

Two small agent skills next to `fpv-best-laps`, for after a best-3-laps clip has been verified.

### Skill: upload the best-laps clip to YouTube (done)

`skills/racegow-youtube/` (`scripts/yt_upload.py`: `auth`, `channel`, `meta`, `upload`, `record`),
built from the prototype that made the first two uploads by hand on 2026-10-12, both public on the
papfpv channel (@niuk9290): https://youtu.be/GG7-ezzppak (RaceGOW6 Track 2, 41.43 s) and
https://youtu.be/zNN1ugb4v4I (RaceGOW6 Track 1).

- [x] Title `RaceGOW6 Track 2 | 41.43s best 3 consecutive laps | PAPFPV`: RaceGOW/track numbers
  from the folder names, time from `result.json`.
- [x] Description in the approved order: result and splits; pilot and leaderboard rank (runs the
  leaderboard skill, per track; the top/bottom half stays out of the
  description, it's only in the leaderboard report); quad, video system (from the file names)
  and date flown (`creation_time`, else file time); sponsor sentence and deadline read from the
  demo video's description with `yt-dlp`; demo link with the flythrough start from the track
  README; racegow.com home, leaderboards (with the sheet's sponsor) and Discord; credit line to the
  repo; hashtags. Every part has an override flag, and missing parts are listed as warnings.
- [x] Tags, category 17 (Sports), not made for kids.
- [x] Auth: desktop OAuth client, port 8765, printed consent URL, token in
  `~/.config/racegow-youtube/token.json` (600), auto-refresh. Cloud project setup documented.
- [x] Approval: the agent shows title/description first; `--privacy` is required on each upload;
  `--expect-channel` must match the token's channel or nothing is uploaded; no second upload of the
  same meta without `--again`. Resumable upload with progress.
- [x] URL saved in the meta JSON, `result.json` (`uploads`) and the track README results table
  (`record` for videos uploaded some other way).
- [x] Tested 2026-10-13 without uploading: `meta` on Track2-1st reproduces the approved Track 2
  description (with the real rank instead of the Reg#), `channel` reads papfpv / @niuk9290, the
  README update on a scratch copy.
- [x] First real upload through the skill, 2026-10-14: RaceGOW6 Track 2 batch `2nd`, 42.73 s,
  public on papfpv (@niuk9290), https://youtu.be/A9BhtjgHdIw.
- Decided: videos already on YouTube stay as they are; the skill is for future uploads.
- Moved to TODO.md (follow-ups): craft name from the OSD.

### Skill: find the pilot's current RaceGOW leaderboard position (done)

`skills/racegow-leaderboard/` (`scripts/leaderboard.py`, standard library only).

- [x] Source: the leaderboards page embeds a public Google Sheet (one tab per track, `Track1`, ...),
  read as CSV, so no headless browser is needed. The sheet id is found from the page each run.
- [x] Match by Reg# (300) or nickname (`papfpv`, ignoring case and punctuation). The sheet's Rank
  column is `TBD` until the livestream, so the rank is computed from `Unofficial Time`, per pilot
  (best time per nickname) and per entry. First run, 2026-10-13: Track 1, 30.770 s,
  **223rd of 343 pilots**, bottom half (226th of 353 entries). Times under 16 s are hidden until the deadline.
- [x] JSON output (`rank`, `of`, `time`, `track`, `fetched_at`, source, per-track details) via `--out`.
- [x] Clear exit codes: 2 pilot not found, 3 page/sheet layout changed.
- [x] Top/bottom half of all pilots (`half`, `top_percent`).
- [x] Tested through the agent skill (2026-10-13 13:18 UTC): Track 1, 223rd of 343, bottom half
  (top 65 %). Only the Track1 tab has times so far; the others say "Coming Soon".
- Moved to TODO.md (follow-ups): re-test when the Track 2 tab gets times.
- [x] The YouTube upload skill runs it for the description; the JSON also carries the sheet title (sponsor).
