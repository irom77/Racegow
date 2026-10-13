# TODO

## Remove hard-coded local paths

These files contain absolute paths from the original development machine (including a Windows
username). They work only there and expose local directory names in a public repo.

- [ ] `src/extract.py`: `SRC` (Windows video folder under `/mnt/c/Users/...`) and `OUT`
  (`/home/irom/RaceGow6/work/feat`). Replace with command-line arguments or environment variables.
- [ ] `src/analyze.py`: `FEAT`, `CENT` (`work/cent_all.npy`) and the `analysis.json` output path.
  Same fix. Note `cent_all.npy` is not committed; point to `skills/fpv-best-laps/assets/osd_digits.npz`
  instead, or mark `src/` as an archived prototype.
- [ ] Check the remaining `src/` modules (`gatematch.py`, `redtrack.py`, `lapdtw.py`, `osd.py`) for
  the same pattern: `grep -rn "/mnt/c\|/home/" src/`.
- [ ] `skills/fpv-best-laps/evals/evals.json`: the test prompt names a personal video folder.
  Replace with a placeholder such as `/path/to/videos`.
- [ ] Optional: rewrite git history (`git filter-repo`) if the old paths should disappear from
  earlier commits too, not just the latest one.

## Feature: verify a run from a YouTube URL

Let a pilot (or race organiser) point the tool at a YouTube video and get the 3-lap time and lap
splits verified, e.g. to check a leaderboard submission.

- [ ] New input: `--url <youtube-url>` on `analyze`/`run` (and a dedicated `verify` command), as an
  alternative to `--videos`. Download with `yt-dlp` into `<work>/source/`, picking the highest
  frame rate available (60 fps if offered) and keeping the original resolution.
- [ ] Optional claimed result: `--claim 30.82` or `--claim 10.27,10.33,10.22`. Report whether the
  detected best 3 consecutive laps match within a tolerance (default ±0.05 s per lap at 60 fps,
  scaled for lower frame rates), and flag mismatches with the source timestamps to review.
- [ ] Optional `--start hh:mm:ss --end hh:mm:ss` to restrict analysis to part of a long video
  (YouTube uploads often contain several packs, intros or edits).
- [ ] Handle uploaded-video differences: 30 fps or variable frame rate (normalise or read real
  timestamps), heavier compression (OSD OCR thresholds), cropped/scaled OSD, and edits/cuts in the
  middle of a run (detect jumps in the OSD timer and reject laps that span a cut).
- [ ] Verification output: a `verify.md` with verdict (verified / mismatch / not verifiable), detected
  vs claimed splits, the crossing contact sheets, and timestamp links back to the video
  (`https://youtu.be/<id>?t=<seconds>`) for each gate crossing.
- [ ] Single-video calibration is the weak spot (see `references/method.md`): allow `--track` with a
  profile from the pilot's own footage of the same layout, and document that the verdict is less
  certain without one.
- [ ] Docs: SKILL.md workflow branch for URLs, README usage example, `yt-dlp` in requirements and
  `doctor`. Note YouTube's terms of service: only analyse videos you own or have permission to use.

## Feature: show the date with the live lap clock

Add the session date to the overlay, next to (or under) the live lap clock, so exported clips show
when the run was flown.

- [ ] Date source, in order: `--date YYYY-MM-DD` override, the container's `creation_time`
  (ffprobe), then the file's modification time. Many goggles/DVRs have no real-time clock (HDZero
  files can carry a default date), so ignore implausible dates (e.g. before 2015) and fall back.
- [ ] Store the chosen date and its source in `result.json`, and show it in `report.md`.
- [ ] Render it in both renderers, left-aligned with the rest of the panel: HyperFrames
  (`assets/overlay/index.html`, new `__DATE__` placeholder) and OpenCV (`render.py`).
- [ ] Format option `--date-format` (default `%Y-%m-%d`), and `--no-date` to hide it.
- [ ] Docs: SKILL.md render step and README options table.

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
- [ ] Optional: `--music-seed N` to re-create a generated track the pilot liked.

## Feature: race commentary in the exported clip (optional)

Energetic, race-caster style commentary over the clip, built from the real lap data, so every clip
sounds different and calls what actually happened. Can be used alone or on top of a quiet music bed.

- [ ] Event timeline from `result.json`: takeoff/first crossing, each gate crossing with its lap
  time, the final total, and context (personal best, rank, gap to the next-best window).
- [ ] Script: short, punchy lines timed to land on the crossings (the clip is only ~30 s). Written by
  an LLM (Claude) for variety, with fixed templates as an offline fallback (`--commentary-style
  template`). Keep each line short enough to finish before the next event.
- [ ] Voice: text-to-speech, default `hyperframes tts` (no extra install); optional cloud voice
  (ElevenLabs / OpenAI) for a more excited caster sound, behind an API key.
- [ ] Mix: each line starts at its event; motor audio turned down while the voice speaks (and the
  music bed too, if `--music` is also set). Reuses the music feature's single `ffmpeg` mix pass.
- [ ] Off by default; enable with `--commentary`. Save the script with timestamps as
  `<work>/export/commentary.txt` so it can be reviewed or edited and re-rendered.
- [ ] Docs: SKILL.md render step and README options table.

## Feature: read the track folder README automatically

Each track folder (e.g. `RaceeGow6/Track2/`) has a `README.md` with the organiser's demo video, the
time its flythrough starts, and one lap the pilot knows is correct. Batches live in subfolders
(`Track2/1st`, `Track2/2nd`, ...). Let the tool pick all of that up, so timing a new batch is just
`fpvlaps.py run --videos Track2/2nd` with no flags.

- [ ] Define a small, documented README format, e.g. lines `Demo: <url>`, `Flythrough: 1:00`,
  `Correct lap: 1st/hdz_0022 at 0:59` (video path relative to the track folder, time in the video).
- [ ] When `--videos` is a batch folder, look for `README.md` in the folder and its parent. Use, in
  order: `--track`/`--anchor` from the command line, then `track.json` next to the README, then
  the README's `Correct lap` (converted to an anchor frame, snapped to the nearest start-gate
  crossing), then automatic calibration.
- [ ] Allow the correct lap to be in a different batch folder than the one being timed (extract
  features for that one video only).
- [ ] After a run that the user or agent has verified, offer to save `track.json`/`track.npz` next to
  the README (a `--save-track` flag), so later batches reuse it.
- [ ] Put the demo link and flythrough time in `report.md`, next to the verification sheets, as the
  reference to check the winning laps against.
- [ ] Docs: SKILL.md workflow (read the README first, check laps against the demo), README usage
  example with a track-folder layout, and a template track README.

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
- [ ] First real upload through the skill (next verified clip).
- Decided: videos already on YouTube stay as they are; the skill is for future uploads.
- [ ] Craft name from the OSD instead of the `--quad` default (Air65).

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
- [ ] Re-test when the Track 2 tab gets times (the latest track should become the top-level result).
- [x] The YouTube upload skill runs it for the description; the JSON also carries the sheet title (sponsor).
