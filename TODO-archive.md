# TODO archive

Completed items moved out of [TODO.md](TODO.md), kept for the decisions and test notes. Open follow-ups from these features stay in TODO.md.

## Remove hard-coded local paths (done)

- [x] Moved the original prototype from `src/` to `legacy/` with a README pointing to the skill.
- [x] Replaced the local folders in `legacy/extract.py` and `legacy/analyze.py` with placeholders
  (`/path/to/videos`, relative `work/...`). The old paths remain in earlier commits; see the
  `git filter-repo` item in TODO.md.
- [x] `skills/fpv-best-laps/evals/evals.json`: test prompt now uses `/path/to/videos`.

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
