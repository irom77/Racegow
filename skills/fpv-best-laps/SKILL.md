---
name: fpv-best-laps
description: Find the fastest 3 consecutive clean laps in a folder of raw FPV / tiny-whoop race recordings (HDZero, DJI, Walksnail, analog DVR) and export that clip with a left-aligned overlay showing the total and each lap time. Parses the Betaflight OSD timers, detects the start gate, filters out crash laps, runs a sliding best-3-consecutive window across every video, and renders with HyperFrames (or an OpenCV fallback). Use this whenever someone wants lap times, best laps, fastest consecutive laps, a lap-timer overlay, or a highlight clip from drone race / RaceGOW / whoop track footage, even if they only say "time my laps" or point at a folder of hdz_*.mp4 files.
compatibility: Python 3.9+ with opencv-python-headless, numpy, imageio-ffmpeg. Optional for the HTML renderer - Node.js (npx) plus ffmpeg and ffprobe on PATH.
---

# FPV best 3 consecutive laps

Turns a folder of raw FPV recordings into: a ranked lap analysis, verification images, and an MP4 of
the fastest **3 consecutive clean laps** with the total and the three lap times on the left side.

Everything heavy is done by `scripts/fpvlaps.py`. Your job is to run it, check its verification sheets,
correct the start gate if needed, and report back. The commands below are plain shell, so they work
from any agent or a terminal. `<skill-dir>` means the folder that contains this SKILL.md.

## Race rules (fixed, don't change them)

- A result is **exactly 3 consecutive laps** in one recording. Lap n+1 starts at the gate crossing
  where lap n ended.
- Laps start and end at the **start gate**. Every recording begins with the quad parked in front of it.
- **Clean** laps only: no crash, no disarm, no stop, and the lap follows the normal racing line.
- The best result is the minimum 3-lap total over a sliding window across all videos.
- The export has the overlay (total + lap 1/2/3) **left-aligned on the left edge** of the frame.

## Workflow

### 1. Set up (once per machine)

```bash
python3 -m venv .fpvlaps-venv
.fpvlaps-venv/bin/pip install -r <skill-dir>/scripts/requirements.txt   # Windows: .fpvlaps-venv\Scripts\pip
.fpvlaps-venv/bin/python <skill-dir>/scripts/fpvlaps.py doctor
```

If an environment with `opencv-python-headless`, `numpy` and `imageio-ffmpeg` already exists, use
its Python instead of creating `.fpvlaps-venv`. `doctor` reports the renderer it will use. HyperFrames needs `npx`, `ffmpeg` and `ffprobe` on PATH.
Without them the OpenCV renderer is used: same layout, plainer typography. Mention which one was
used when you report.

### 2. Analyze the folder

```bash
.fpvlaps-venv/bin/python <skill-dir>/scripts/fpvlaps.py analyze --videos "<folder>" --work "<work dir>"
```

- Paths with Windows drive letters work as-is on Windows. Under WSL use `/mnt/c/...`.
- Feature extraction decodes every frame once, in parallel across videos (measured: 36 min of 720p60
  HEVC in about 15 min on a 22-core machine, reading from a Windows drive under WSL). Results are cached in
  `<work>/features/`. A re-run (e.g. with `--anchor`) skips extraction but still spends 1-3 min on
  calibration and lap matching. Run it in the
  background if your agent supports that, and tell the user roughly how long it takes.
- Output in `<work>`: `report.md` (result + runners-up + per-video summary), `laps.csv` (every lap
  with clean/reason), `result.json`, `track.json` (reusable track profile), `sheets/*.jpg`.

### 3. Verify before exporting

The analysis is automatic, but the start gate is learned from the footage. Check it before
spending time on a render. If you can view images, open:

- `sheets/reference_lap.jpg`: two rows, the reference lap's start and end crossings (outlined X frames).
  Both rows must show **the same place on the track, at the start gate** (the gate the quad was parked
  in front of at the start of every video). If they show a different spot, the timing line is wrong.
- `sheets/rank1_crossings.jpg`: the 4 crossings of the winning window. All 4 rows should look alike.
  (`rank2_crossings.jpg` and `rank3_crossings.jpg` cover the runners-up. Check the one you fall back to.)

If you can't view images, say so and ask the user to glance at those two files.

**If the gate is wrong**, pick a frame where the quad passes the start gate during a lap. Find
candidates in `laps.csv`, or by looking at the footage. Then re-run with a manual anchor
(extraction is cached, so this takes 1-3 min):

```bash
... fpvlaps.py analyze --videos "<folder>" --work "<work>" --anchor hdz_0024:1596
```

If `report.md` starts with **"Warning: the reference lap looks wrong"**, the laps it found don't fit
the track: they're much shorter than the track's lap period (the reference skips part of the
course, e.g. a dive, so laps that skip it pass as clean), or consecutive laps don't share their
crossings (the reference doesn't start and end at the start gate). Don't render. Find a start-gate crossing that begins a full, correct
lap (ask the user for one if needed) and re-run with `--anchor`.

**If the track has an official layout** (e.g. the organiser's demo flythrough video, often linked in
a README in the track folder), it is the real reference: the tool only compares laps with each
other and can't tell a consistently wrong line from the right one. Before rendering, check the
winning laps against it, gate by gate.

Also read `report.md`. If it has a **"Check before trusting"** block, one of the winning laps is
much faster than the track's typical lap, which usually means a missed or re-flown gate. Look at
`sheets/rank1_crossings.jpg`. If a row shows a different spot from the others, fall back to the
next rank whose sheet is consistent, render it with `--rank N`, and say why rank 1 was rejected.

### 4. Export

```bash
.fpvlaps-venv/bin/python <skill-dir>/scripts/fpvlaps.py render --work "<work dir>" [--rank 1] [--renderer auto|hyperframes|opencv]
```

Always pass `--rank` explicitly (the rank you verified). Rendering takes minutes, so run it in the
background if your agent can: HyperFrames took 5-12 min for a 33 s clip on a CPU-only machine, and
the OpenCV renderer 3-10 min, mostly cutting and encoding from a slow drive.

The output is `<work>/export/best3_laps_<video>_<total>s.mp4`. The source frames are cut
frame-accurately, with 1 s before the first crossing and 1 s after the last (`--lead`), keeping the
original audio. `--title` changes the overlay subtitle.
If the user wants it somewhere specific, copy the file there.
The overlay counts up live: mid-clip frames show the running lap and total, and laps not yet flown
show 0.00s. Check the last second of the clip to see the final numbers.

`run` = `analyze` + `render` in one go, for when the user doesn't want the verification stop.

### 5. Report

Tell the user the result as a small table: video, lap 1/2/3, total, and the time span in the source
video (from `report.md`, which lists frames and video times for every rank). Give the export path, how many videos and laps were analyzed and how many laps were rejected
(and the main reasons), and the next-best total. If you rejected a rank, report the next valid rank after the one you exported
and explain the rejected one separately. Say plainly whether you verified the sheets. Lap
times are accurate to about ±2-3 frames (±0.05 s at 60 fps).

## Same track again

Calibration is saved to `<work>/track.json` + `track.npz`. For more sessions on the same layout, pass
`--track <old work>/track.json` to skip calibration and time laps against the same reference. This is
also more reliable when the new folder holds only 2-3 videos, since a profile built from a bigger
session is steadier. A new layout needs a fresh calibration: just run without `--track`.

## When things go wrong

| Symptom | What to do |
|---|---|
| "No parked start found" / "Could not find a repeating lap pattern" | Footage doesn't start parked at the gate, or there are too few laps. Use `--anchor VIDEO:FRAME`. |
| A video shows `armed via motion (no OSD timer found)` | No `mm:ss` timer is on screen, or the OSD font differs from Betaflight's default. Laps still work. Disarm detection then relies on motion only. |
| No 3-lap result | Not enough consecutive clean laps. Check `laps.csv` reasons, then `--rank` / the runners-up. |
| HyperFrames render fails | Re-run with `--renderer opencv`, and report the HyperFrames error. |

How the detection works and which knobs exist (`scripts/fpvlaps/config.py`): see
`references/method.md`. Read it when the results look wrong or the footage is unusual (different
OSD, different frame rate, no parked start).
