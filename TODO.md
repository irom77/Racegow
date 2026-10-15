# TODO

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
- [ ] Verify: a variable-frame-rate upload (the CFR re-encode is untested on real VFR footage).
- [ ] Verify: digit templates for the wide OSD layout (40 px pitch). Other pilots' uploads misread
  about 1 digit in 4 with the default-font templates (`0` as `3`, seconds 5-9), so those timers are
  used for edit checks only, not arm detection. Keep them separate from `osd_digits.npz`.
- [ ] Verify: read the anchor from a clip's own lap-timer overlay automatically (today: by hand,
  `frame - clock x fps`).
- [ ] Verify: start-line precision for uploads without an overlay clock. RealSco's
  https://youtu.be/wqoGGwFT4bo (33.70 s) gives 33.58 s at anchor 186 and 34.02 s at 160 (gate pass
  spans ~156-190); refine the anchor against the lap's own finish crossing instead of using it as given.
- [ ] Verify: `--crop` or overlay masking for uploads with a burned-in overlay or a different crop
  (today the raised match cost is accepted only when it is uniform across the upload).
- [ ] Leaderboard skill: re-test when the Track 2 tab gets times (the latest track should become the
  top-level result).
