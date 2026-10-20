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

## Feature: sector splits and theoretical best (done)

Time each section of every clean lap, so the pilot sees where a lap is won or lost. Only possible
because every lap is already aligned to the reference lap (subsequence DTW); a manual gate-marking
tool can't do this. Details in [TODO-archive.md](TODO-archive.md).

- [x] Split the reference lap into 3-4 sectors: evenly by default, or at frames given with
  `--sectors F1,F2,...` and saved in `track.json`.
- [x] Map each sector boundary into every clean lap through the DTW path and time each sector.
- [x] Per-sector best, and the theoretical best lap made of those best sectors.
- [x] `result.json`: per-lap sector times. `report.md`: a sector table with the best in each
  sector highlighted, plus the theoretical best against the real best.
- [x] Docs: SKILL.md, method.md and the README.

## Feature: side-by-side lap comparison (done)

Inspired by [FPV DVR Lap Timer](https://github.com/lenuxfpv/fpv-dvr-lap-timer)'s "Compare two
laps". Details in [TODO-archive.md](TODO-archive.md).

- [x] `compare --lap VIDEO:LAP --lap VIDEO:LAP` (laps from the same or different sessions of a
  track): render both side by side, each starting on its own gate frame, with both lap clocks.
- [x] Running gap at every point of the lap via DTW alignment (not only at the finish), e.g.
  "+0.4 s after the dive". Show sector deltas once sector splits exist.
- [x] Default pair: the best lap of this session against the best lap ever on the track.
- [x] Both renderers (HyperFrames and OpenCV), no audio or a single audio track.

## Feature: progress across sessions and consistency stats (done)

Inspired by FPV DVR Lap Timer's progress and consistency charts. No database: read the saved
`result.json` files. Details in [TODO-archive.md](TODO-archive.md).

- [x] `history --track TrackN`: collect every session's `result.json` for the track and chart best
  lap, best 3, median clean lap and clean-lap % over time (static HTML, linked from `report.md`).
- [x] Consistency in `report.md`: standard deviation of clean laps, gap between best and median
  lap, crash/bad-lap rate.

## Smaller ideas from FPV DVR Lap Timer

- [ ] Manual corrections that stick across re-runs: nudge a gate crossing by ±N frames, force a lap
  clean or bad (today only `--anchor`). The `rankN_crossings.jpg` sheets show what to check.
- [ ] Export extras: intro card with pilot handle / sticker, configurable padding before and after,
  move or hide parts of the overlay.
- [ ] Best N consecutive laps (2-10), not only 3: check whether `laps_per_result` is already wired
  to a CLI option.
- [ ] Incremental runs: notice new `hdz_*` files in a track folder and process only those.

## Follow-ups from finished features

The finished features are in [TODO-archive.md](TODO-archive.md).

- [ ] Sectors: show the sector times in the clip overlay (a split as each boundary is passed), and
  the theoretical best per session in `history`.
- [ ] Sectors: name the boundaries in the track README (e.g. `**Sectors:** 3700 dive, 3950 cube`).
  `compare` would then say "+0.4 s after the dive" instead of "from 5.4 s to 6.9 s (S2)".
- [ ] Compare: make the HyperFrames render faster (14.8 min for a 15.8 s clip vs 41 s for OpenCV, so
  `auto` uses OpenCV): e.g. pre-composite both videos into one clip and keep only the overlay in HTML.
- [ ] Compare: a ghost view (lap B as a small picture-in-picture over lap A), and comparing best-3 runs,
  not only single laps.
- [ ] History: show the session dates from the date feature (`result.json`) once it exists; today
  they come from a `YYYY-MM-DD` batch folder name, the recordings' file dates or the first analysis.
- [ ] History: lap-time spread per session (box or strip of every clean lap), and per-pack points
  within a session.
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
