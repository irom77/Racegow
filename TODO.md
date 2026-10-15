# TODO

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

## Follow-ups from finished features

The finished features are in [TODO-archive.md](TODO-archive.md).

- [ ] Background music: `--music-seed N` to re-create a generated track the pilot liked.
- [ ] YouTube upload skill: craft name from the OSD instead of the `--quad` default (Air65).
- [ ] Leaderboard skill: re-test when the Track 2 tab gets times (the latest track should become the
  top-level result).
