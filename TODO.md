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
- [ ] Test-render one clip with `--renderer opencv` (only HyperFrames was test-rendered; the blur is
  in the shared cut, so it should match).
- Decided: clips already on YouTube keep their black bars (no re-upload); new clips get the blur.

## Feature: background music in the exported clip (optional)

The raw clip only has motor noise. A music bed makes it shareable. Keep it simple.

- [ ] Option `--music <file>` to mix a track under the clip, and `--music auto` to pick a random
  royalty-free track from a small bundled set (check each track's licence allows redistribution in
  a public repo; otherwise download on demand or generate one).
- [ ] Mix: music trimmed to the clip length, fade in/out (~1 s), motor audio kept but turned down
  (around -12 dB, adjustable with `--source-volume`). One `ffmpeg` pass, the same for both renderers.
- Decided: **off by default** (no music, original audio kept, e.g. for race-verification clips).
  The mix above is applied only when music is asked for (`--music`).
- [ ] Docs: SKILL.md render step and README options table.

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

### Skill: upload the best-laps clip to YouTube

Upload the exported clip to the pilot's YouTube channel (pilot nickname **PAPFPV**). The channel is
whichever one the pilot picks at the Google sign-in; the first upload went to **niuk**
(@niuk9290), not youtube.com/irom77.

**Status: in progress.** Two uploads were done by hand with a prototype script on 2026-10-12, both
public on niuk: https://youtu.be/GG7-ezzppak (RaceGOW6 Track 2, 41.43 s) and
https://youtu.be/zNN1ugb4v4I (RaceGOW6 Track 1). The prototype, `yt_upload.py` (`auth` and
`upload` commands, google-api-python-client + google-auth-oauthlib), is outside the repo. What's left is turning it into a skill that builds the title and description by itself.

- [ ] Title includes: the current RaceGOW number, the track number, the 3-lap time and `PAPFPV`,
  format `RaceGOW6 Track 2 | 41.43s best 3 consecutive laps | PAPFPV`. Take the RaceGOW/track
  numbers from the track folder (README or `result.json`), the time from `result.json`.
- [ ] Description, in this order (the approved first upload is the template): the result and lap
  splits; pilot `PAPFPV` and current RaceGOW rank (from the leaderboard skill below; 300 on
  2026-10-12); quad and video system (craft name from the OSD, e.g. Air65 · HDZero) and the date
  flown; "About the race": track sponsor/designer and deadline (from the organiser's demo video
  description; racegow.com/home doesn't list per-track details), the demo flythrough link with its
  start time, racegow.com home, leaderboards and Discord links; a credit line linking
  https://github.com/irom77/Racegow; `#RaceGOW #tinywhoop #fpv`.
- [ ] Tags: RaceGOW, RaceGOW<N>, tiny whoop, whoop racing, FPV, quad name, video system, PAPFPV,
  track sponsor. Category 17 (Sports), not made for kids.
- [x] Prove the API flow end to end: OAuth sign-in, channel check, resumable public upload (done by
  hand with the prototype for the first video).
- [ ] Auth: YouTube Data API v3, desktop OAuth client (`client_secret_*.json`, redirect
  `http://localhost`), scopes `youtube.upload` + `youtube.readonly` (to confirm the channel). The
  consent URL is printed (no browser on WSL) and the local callback listens on port 8765. Token in
  `~/.config/racegow-youtube/token.json` (mode 600, never in the repo); refresh it automatically.
  Document: enable the API in the Cloud project, add the pilot as a test user while the app is in
  testing mode.
- [ ] Always show the title/description for approval before uploading. Privacy is the pilot's call
  on each upload (`--privacy private|unlisted|public`); the first upload was approved as
  **public**. Resumable upload with progress.
- [ ] Return the video URL and save it in `result.json` and the track README results table (done
  by hand for the first upload).
- [ ] Before uploading, check the channel name the token points to and confirm it with the pilot.

### Skill: find the pilot's current RaceGOW leaderboard position

- [ ] Read https://www.racegow.com/leaderboards and find `PAPFPV` (match case-insensitively, allow
  for variants of the nickname). Report the overall rank, and per-track rank and time if listed.
- [ ] The page may be rendered with JavaScript: try a plain fetch first, fall back to a headless
  browser (Playwright) if the table isn't in the HTML.
- [ ] Output a small JSON (`rank`, `of`, `points`/`time`, `fetched_at`, source URL) that the upload
  skill reads for the video description.
- [ ] Say clearly when the pilot isn't found or the page layout changed, instead of guessing.
