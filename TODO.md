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

## Feature: blurred background in the exported clip

HDZero (and other 4:3) footage sits in a 16:9 frame with black bars on the sides, and the lap panel
sits on top of the picture. Fill that space with a blurred, darkened copy of the footage so the clip
looks finished and the overlay reads better.

- Decided: blur the **side bars only** (a blurred, scaled-up, darkened copy of the footage behind the
  sharp 4:3 picture). It is the simplest and fastest to render in both renderers; the lap panel stays
  as it is. A frosted backdrop behind the panel can come later if wanted.
- [ ] Detect the active picture area per video (the black bars are already known: 4:3 picture at
  x160..1120 in 1280x720) instead of hard-coding it.
- [ ] HyperFrames renderer: a second `<video>` layer scaled to cover, with CSS `filter: blur()`
  and dimming, under the sharp footage (`assets/overlay/index.html`).
- [ ] OpenCV renderer: same result with `cv2.GaussianBlur` on a downscaled frame (cheap), then
  composite (`render.py`).
- [ ] Option `--background blur|black` (default `blur` once it looks right), `--blur-strength`.
- [ ] Update the skill: SKILL.md render step, README options table, and refresh
  `docs/overlay-final.jpg`.

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
