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

## Smaller ideas from FPV DVR Lap Timer

- [ ] Manual corrections that stick across re-runs: nudge a gate crossing by ±N frames, force a lap
  clean or bad (today only `--anchor`). The `rankN_crossings.jpg` sheets show what to check.
- [ ] Export extras: intro card with pilot handle / sticker, configurable padding before and after,
  move or hide parts of the overlay.
- [ ] Best N consecutive laps (2-10), not only 3: check whether `laps_per_result` is already wired
  to a CLI option.
- [ ] Incremental runs: notice new `hdz_*` files in a track folder and process only those.

## ghostline: evaluate and borrow

[Saqoosha/ghostline](https://github.com/Saqoosha/ghostline) reconstructs the 3D flight path from DVR on a
Gaussian-splat scan of the venue. Findings and the comparison with this tool are in
[docs/ghostline-comparison.md](docs/ghostline-comparison.md). There's no local GPU, so the plan is:
read and borrow first (CPU only), then one paid RunPod trial if it still looks worth it.

### 1. Read (no GPU, free)

- [ ] Watch the [MGP Champs replay](https://ghostline.saqoo.sh/mgp-champs-2026/): how useful is a 3D
  line compared with our lap/sector `compare`?
- [ ] Machine-translate `docs/dvr-localization.ja.md` and `CLAUDE.md` (its list of costly mistakes).
  Note anything that also applies to whoop DVR: OSD masks, fisheye lens, 60 fps jitter.
- [ ] Check whether Blastaa's fork ("extra harnesses") is public yet. On 2026-10-26 the forks
  `skermiebroTech/ghostline` and `kirek007/ghostline` had no extra commits. Ask on the RaceGOW Discord
  whether anyone has tried it indoors or on a whoop.

### 2. Borrow (no GPU)

- [ ] **Flythrough check** (main idea): match frames of the best-3 laps against the organiser's demo
  flythrough named in the track README, using 2D features (ORB/SIFT in OpenCV, CPU), and check that
  the gate sequence lines up. This catches a consistently wrong line, such as a skipped dive, that
  the tool can't see today. Report it as a warning like the existing reference-lap checks. Try it
  first on Track 2 (hdz_0022 vs PqOFU-AwNvU at 1:00) and Track 3 (hdz_0025 vs PDvWKWs_0j4 at 1:38),
  both verified. Add a known-bad lap to make sure it fails.
- [ ] Decision log like their `choice.txt`: write to `report.md` why the reference lap and the
  anchor were chosen (auto, `--anchor`, or `track.json`), so a wrong result is easier to trace.
- [ ] Takeoff without OSD: they detect takeoff when the change between frames stays above 2.5x the
  idle level for 0.5 s. That could serve as a fallback arm detector for analog footage with no
  readable OSD timer.
- [ ] A "costly mistakes" section in `skills/fpv-best-laps/SKILL.md` (like their CLAUDE.md), so
  agents don't repeat known errors (e.g. the Track 2 GIF that shows the wrong layout).

### 3. Trial on RunPod (paid, only if 1–2 still say it's worth it)

Goal: one 3-lap clip reconstructed in 3D on one RaceGOW track. Budget: a few hours on one 24 GB GPU
(RTX 4090 or A5000 class, roughly $0.5–0.7/h; check current prices).

- [ ] Scan the track room: a slow phone video walk-through covering every gate from several heights
  and angles, with good light and the layout exactly as flown. Start with the smallest track.
- [ ] Lens: the repo ships profiles only for the HDZero Nano 90 (stock and upgrade lens). Check which
  camera the whoop uses. If it's different, calibrate it first (`tools/dvr/calib.py`, checkerboard
  DVR clip).
- [ ] Pod setup: CUDA image with COLMAP, gsplat 1.5.3, MASt3R, DINOv2. Expect porting work, because
  scripts hardcode the author's machines (`win4090`, `/mnt/c/...`, `~/mastenv`). Keep the setup as a
  script so the pod can be thrown away and rebuilt. Maybe use Blastaa's fork if it's public by then.
- [ ] Build the splat from the scan (see how [VDGS](https://github.com/Saqoosha/VDGS) does it, or
  `tools/theta/` for video input), with real-world scale (measure one gate).
- [ ] Run `FPS=30 T0=<s> DUR=<s> tools/dvr/dvr_pipeline.sh` on the Track best-3 clip only (about
  45 s), not the whole DVR file.
- [ ] Judge it: does the path stay inside the room, pass every gate in order, and take off from the
  start pad? Do the 3 laps overlay closely? Note the GPU time and cost.
- [ ] If it works: decide whether to add an optional `export_path` step (Racegow lap boundaries →
  ghostline poses → a line per lap), or just link to ghostline. If it doesn't: write down why
  (indoor, repeated gates, lens) in docs/ghostline-comparison.md.

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
