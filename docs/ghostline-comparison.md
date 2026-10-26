# ghostline vs. Racegow

Notes from reviewing [Saqoosha/ghostline](https://github.com/Saqoosha/ghostline) (2026-10-26), which
Blastaa shared on the RaceGOW Discord. It was a read-only review: nothing was installed or run.

## What ghostline is

ghostline takes a pilot's goggle DVR recording (HDZero), works out where the drone was in 3D for every
frame on a 3D Gaussian Splatting (3DGS) scan of the same venue, and replays the flight in a web viewer.
It can show a single flight beside its DVR, or a whole heat with every pilot's line.

- Demo, the full 2026 MultiGP Championship: <https://ghostline.saqoo.sh/mgp-champs-2026/> (GPU heavy in the browser)
- Viewers: <https://ghostline.saqoo.sh>
- Licence: MIT. Python for the pipeline, TypeScript (Vite + PlayCanvas) for the viewers, a Cloudflare
  Worker with R2 for hosting.
- The venue scans come from a sister project, [Saqoosha/VDGS](https://github.com/Saqoosha/VDGS).
- Most of the documentation is in Japanese (`docs/dvr-localization.ja.md`, `docs/realtime-tracking.ja.md`).

### Offline pipeline (`tools/dvr/dvr_pipeline.sh`)

1. `undistort.py`: turns the HDZero fisheye video into a 100° pinhole video and masks out the OSD.
2. `cpr_track.py`: renders the scan from a predicted pose and matches it against the DVR frame with
   MASt3R, then solves the camera position (PnP with RANSAC) one frame at a time. DINOv2 finds the
   position again when tracking is lost.
3. `cpr_ba.py`: bundle adjustment over all frames at once, limiting motion by jerk rather than
   acceleration. At 60 fps, a 1.5 cm wobble between frames looks like about 100 m/s² of acceleration,
   more than a real racing move (around 30 m/s²). Jerk separates the two.
4. `cpr_rematch.py`, the second pass: renders again from the solved poses and re-matches. This fixes
   a common error where the many nearby grass points line the pose up and the few distant poles and
   trees get thrown out as outliers.
5. `takeoff.py`: detects takeoff and fixes the path on the start pad.

The whole run takes roughly 2 hours of GPU time per flight on an RTX 4090. It needs MASt3R, gsplat 1.5.3
and COLMAP.

### Live mode (`tools/dvr/rt_*`)

The live mode tracks up to 4 pilots from the video feeds (SRT or NDI) at about 60 fps each, using
TensorRT engines (LighterGlue, XFeat) on an RTX 4090. It shows the result to spectators at the event
through a control page, an OBS overlay and a WebSocket feed. There is also an iPhone AR app that places
the scan and the flight paths in the room.

### "The LLM acts as an orchestrator"

The repo is developed and run with Claude Code. It has a `CLAUDE.md`, an `AGENTS.md`, and superpowers
plans and specs under `docs/superpowers/`. About 130 scripts with many settings sit under `tools/dvr/`.
The agent picks which pass to keep for each flight and records why in `choice.txt`. Most of `CLAUDE.md`
is a list of costly mistakes the author has already run into.

As of 2026-10-26, the public forks (`skermiebroTech/ghostline`, `kirek007/ghostline`) have no commits
beyond upstream. The fork Blastaa mentioned building "with extra harnesses" is not public yet.

## Comparison

| | **Racegow (`fpv-best-laps`)** | **ghostline** |
|---|---|---|
| Question it answers | How fast, and was the lap clean? | Where exactly was the quad in 3D? |
| Output | Best 3 consecutive clean laps, lap times, clip with overlay, YouTube upload | 3D flight path for every frame, web replay of a flight or a heat |
| Input | Folder of DVR files only | DVR, a 3DGS scan of the venue, and the lens calibration |
| Setup per track | None (learns the start gate); optional verified `track.json` | Scan the venue, train the splat, set real-world scale |
| Compute | CPU and OpenCV, minutes for an hour of footage | RTX 4090, about 2 h per flight offline (live: TensorRT) |
| Footage | HDZero, DJI, Walksnail, analog | HDZero Nano 90 (stock and upgraded lens profiles) |
| Environment | Indoor whoop tracks, any layout | Large outdoor courses (MultiGP, JDL, FDF) |
| Lap timing | Betaflight OSD timer, frame-accurate, best-3 sliding window | Not the focus; has `official_laps.py` and `finish_gate.json` helpers (not reviewed) |
| Crash / skipped-gate detection | Yes, each rejected lap gets a reason | Not built in; visible in the 3D path |
| Agent role | Claude Code skill: `doctor` → `analyze` → `render`, with checks that refuse an untrustworthy time | Claude Code runs the scripts and picks passes (`choice.txt`) |
| Audience | One pilot submitting a RaceGOW time | Event spectators and post-race review |
| Maturity | Packaged skill, one command, tests | Research notebook: hardcoded paths to the author's machines, many experimental pose files |

The two tools complement each other. Racegow produces the result you submit. ghostline shows the line
you flew.

## What it would take to use ghostline here

- A 3DGS scan of each track room: a phone video, then COLMAP, then gsplat training.
- A CUDA GPU with about 24 GB of memory (the pipeline is tuned for an RTX 4090).
- Indoor whoop tracks are untested. Their notes say tracking can mix up similar-looking views (it
  once confused two identical arches), and a small room full of repeated gates may make that worse.

That is too much setup for a RaceGOW submission.

## An idea worth borrowing

Racegow's main known gap (see the README): it compares your laps with each other, so it can't tell a
consistently wrong line, such as a skipped dive, from the correct one. Today that is checked by hand
against the organiser's demo flythrough.

ghostline's core trick is to render a reference view and match image features against the DVR frame.
Racegow already has a reference without any 3D scan: the demo flythrough video named in each track
folder's README. Matching lap frames against flythrough frames with 2D features (ORB or SIFT, or
LightGlue on a GPU) and checking that the gate sequence lines up could flag skipped gates
automatically. It would turn the manual demo check into another automatic warning. Not implemented yet.
