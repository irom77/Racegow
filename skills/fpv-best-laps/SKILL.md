---
name: fpv-best-laps
description: Find the fastest 3 consecutive clean laps in a folder of raw FPV / tiny-whoop race recordings (HDZero, DJI, Walksnail, analog DVR) and export that clip with a left-aligned overlay showing the total and each lap time. Parses the Betaflight OSD timers, detects the start gate, filters out crash laps, runs a sliding best-3-consecutive window across every video, and renders with HyperFrames (or an OpenCV fallback). Use this whenever someone wants lap times, best laps, fastest consecutive laps, a lap-timer overlay, or a highlight clip from drone race / RaceGOW / whoop track footage, even if they only say "time my laps" or point at a folder of hdz_*.mp4 files. Also, optionally, checks a claimed lap time in a YouTube video (verify --url).
compatibility: Python 3.9+ with opencv-python-headless, numpy, imageio-ffmpeg. Optional for the HTML renderer - Node.js (npx) plus ffmpeg and ffprobe on PATH. Optional for YouTube URLs - yt-dlp.
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
- **Track folder README.** When `<folder>` is a batch inside a track folder (`Track2/2nd`), the tool
  reads `README.md` from the folder or its parent and logs `reference: ...`. It picks the reference
  lap in this order: `--track` / `--anchor`, `track.json` next to the README, the README's
  `**Correct lap:**` line, automatic calibration. The README's demo link and flythrough start go into
  `report.md` ("Reference to check against"). Read that README yourself too: it often has notes
  such as skipped-dive shortcuts. `--no-readme` ignores it, `--readme FILE` picks another one. Format:
  `assets/track-README-template.md`.
- Feature extraction decodes every frame once, in parallel across videos (measured: 36 min of 720p60
  HEVC in about 15 min on a 22-core machine, reading from a Windows drive under WSL). Results are cached in
  `<work>/features/`. A re-run (e.g. with `--anchor`) skips extraction but still spends 1-3 min on
  calibration and lap matching. Run it in the
  background if your agent supports that, and tell the user roughly how long it takes.
- **Sector splits**: every clean lap is also timed in sectors (3 even splits of the reference lap by
  default; `--sectors 4` for another count, `--sectors F1,F2,...` for boundaries at reference-lap
  frames, saved in the track profile). `report.md` lists the fastest laps' sectors, the best per sector,
  the theoretical best lap and where the best-3 laps lose most time; `sheets/sectors.jpg` shows each
  boundary's view. If the pilot wants splits at real track features (a gate, the dive), pick frames
  from the reference lap and re-run `analyze` with `--sectors`.
- Output in `<work>`: `report.md` (result + runners-up + sector splits + per-video summary), `laps.csv` (every lap
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
.fpvlaps-venv/bin/python <skill-dir>/scripts/fpvlaps.py render --work "<work dir>" [--rank 1] [--renderer auto|hyperframes|opencv] [--background blur|black] [--music FILE|auto]
```

Always pass `--rank` explicitly (the rank you verified). Rendering takes minutes, so run it in the
background if your agent can: HyperFrames took 5-12 min for a 33 s clip on a CPU-only machine, and
the OpenCV renderer 3-10 min, mostly cutting and encoding from a slow drive.

The output is `<work>/export/best3_laps_<video>_<total>s.mp4`. The source frames are cut
frame-accurately, with 1 s before the first crossing and 1 s after the last (`--lead`), keeping the
original audio. `--title` changes the overlay subtitle. Black side bars (4:3 footage such as HDZero)
are filled with a blurred, dimmed copy of the footage by default. `--background black` keeps them,
and `--blur-strength` (default 40 px) sets the blur. Music is off by default (the clip keeps its own
audio). Add it only when the user asks: `--music <file>`, or `--music auto` for a generated track;
the music sits 10 dB under the motor audio (`--music-volume`, more negative = quieter).
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

`report.md` also has a **Consistency** table (std dev of clean laps, best vs median lap, bad-lap and
crash rate). Mention it when the pilot asks how consistent the session was. When there are sector splits, add the
theoretical best and the sector where the best-3 laps lose most time.

## Verify a run from a YouTube URL (optional)

When someone gives a YouTube link instead of a folder (e.g. to check a leaderboard submission), use
`verify`. It needs `yt-dlp` (`pip install 'yt-dlp[default]'`, which includes the `yt-dlp-ejs` YouTube needs; YouTube also needs Node.js or deno, which `doctor`
checks). Only analyse videos the user owns or has permission to use (YouTube's terms of service);
say so if it's someone else's video and they haven't said they may use it.

```bash
.fpvlaps-venv/bin/python <skill-dir>/scripts/fpvlaps.py verify --url "<youtube url>" [--claim 30.82 | --claim 10.27,10.33,10.22] [--start 1:20 --end 4:05] [--track <profile>.json | --readme <track>/README.md]
```

- The video is downloaded to `<work>/source/` (default work `./fpvlaps-work/yt_<id>`) at the highest
  frame rate offered, then the original resolution, and analysed as a one-video batch. A variable
  frame rate, a frame rate below 50 fps (doubled, with blended frames), or a `--start`/`--end` section is
  re-encoded at a constant frame rate first.
- `--claim` is the claimed 3-lap total or the 3 lap times. The verdict is decided on the **total**,
  within ±3 frames (±0.05 s at 60 fps, ±0.10 s at 30 fps; `--tolerance` overrides it). Claimed lap
  times are compared at ±0.15 s for information only: pilots time from their own line (a gate, the
  start pad, a lap timer), and a line a few frames further along moves time from one lap to the next
  but not out of the total. Without `--claim` the best clean laps are just reported.
- **Whose track is it?** Each pilot builds the layout at home, so a track profile (`--track`, or the
  `track.json` that `--readme` brings) is only valid for videos flown **on that same build**: the
  user's own uploads. A profile from another room still produces laps (tested: another pilot's
  room matched the user's profile as well as the user's own upload did), so the tool can't catch
  this for you. For anyone else's video, never pass the user's profile or README: use `--no-readme`
  and an anchor from that video.
- **Finding the anchor** (`--anchor <id>:FRAME`, a start-gate pass that begins the run). Uploads
  rarely have the parked start that automatic calibration needs (tested: one starts mid-flight, one
  sits still for only 2.5 s). In order:
  1. **The clip's own lap-timer overlay**, if it has one: read its running clock at two frames
     (e.g. `10.83` at frame 900) and work back to the frame where it read 0
     (`900 - 10.83 x fps`). That is where the pilot started timing.
  2. **The gate pass in the opening seconds**: tile the first ~5 s of
     `<work>/source/youtube/<id>.mp4` every 12 frames with the frame number on each tile (OpenCV,
     like `report.crossing_sheet`), find the launch and the frame where the start gate's frame or
     flag leaves the picture, then tile that range every 3 frames to pin it down.
  Check `sheets/verify_crossings.jpg`: all rows should show the same spot. The anchor is used as
  given, so the first lap moves with it; later crossings are refined and don't.
  If the verdict is a mismatch by about 0.1 s with a hand-picked anchor, report it as "close;
  depends on where the start is placed", not as a wrong claim (RealSco's 33.70 s claim: 33.58 s
  at frame 186, 34.02 s at frame 160).
- If `verify.md` says the reference came from automatic calibration of this one video, say that the
  verdict is less certain.
- Output: `<work>/verify.md` (and `verify.json`) with the verdict (**verified**, **mismatch**, **not
  verifiable**, or **detected** without a claim), detected vs claimed laps, a YouTube link for every gate
  crossing (`https://youtu.be/<id>?t=<s>`), edits found in the footage, and
  `sheets/verify_crossings.jpg`. Look at the sheet before reporting **verified**, as in step 3.
- Edits: a cut in the footage makes the OSD timer jump against the video; laps that span one don't
  count. Without a readable OSD timer, edits can't be ruled out, and `verify.md` says so.
- `--url` also works with `analyze` and `run` (instead of `--videos`); `--claim` on those adds the
  verification step.

Report the verdict, the detected and claimed laps (total and splits), where the anchor came from, and
the links for any lap that didn't match.

## Same track again

Calibration is saved to `<work>/track.json` + `track.npz`. Once the run is verified (sheets checked
against the demo, ideally confirmed by the pilot), save it next to the track README so later batches
pick it up with no flags:

```bash
.fpvlaps-venv/bin/python <skill-dir>/scripts/fpvlaps.py save-track --work "<work dir>"   # --to DIR without a README
```

It refuses to replace an existing `track.json` (other batches may rely on it); `--force` replaces it and
keeps the old one as `.bak`. Ask the pilot before using `--force`. Without a track README, pass
`--track <old work>/track.json` to skip calibration and time laps against the same reference. This is
also more reliable when the new folder holds only 2-3 videos, since a profile built from a bigger
session is steadier. A new layout needs a fresh calibration: just run without `--track`.

## Progress across sessions

When the pilot asks how they're improving on a track, chart every analysed session of it:

```bash
.fpvlaps-venv/bin/python <skill-dir>/scripts/fpvlaps.py history --track "<track folder>"   # or --track Track2
```

It reads `<work-root>/*/result.json` (default `./fpvlaps-work`, change with `--work-root`), keeps the
sessions whose batch folder, track README or profile is inside the track folder, or whose path has a
folder named after the track, and writes `history.html` (best lap, best 3, median clean lap, clean-lap %
per session, plus a table) and `history.json` into the track folder (`--out DIR` to change), and links
it from each session's `report.md`. Session dates come from a `YYYY-MM-DD` batch folder name, else the
recordings' file dates, else the first analysis. Report the trend from the table in a few lines.

## Comparing two laps

When the pilot asks where a lap was faster or slower than another (their best ever, last session's,
a friend's run on the same track), render them side by side:

```bash
.fpvlaps-venv/bin/python <skill-dir>/scripts/fpvlaps.py compare --work <work>        # best lap here vs best on the track
.fpvlaps-venv/bin/python <skill-dir>/scripts/fpvlaps.py compare --lap Track2-2nd/hdz_0023:best --lap Track2-1st/hdz_0022@86.7
```

A lap is `[SESSION/]VIDEO:N` (Nth lap of that video in `laps.csv`), `VIDEO@SECONDS` (as `report.md`
writes laps) or `VIDEO:best`. SESSION is a work directory or its name under `--work-root`. With no
`--lap`, the best clean lap of `--work` is compared with the best clean lap of any session of the same
track (the next fastest if this session holds the record). The two laps are aligned point by point
(DTW), so the gap is known everywhere in the lap, not only at the finish. Output in
`<work>/compare/<A>_vs_<B>/`: `compare.md` (lap table, furthest behind/ahead, where lap A loses and
gains most, sector deltas), `gap.png`, `compare.json` and the video (1920x1080, A left / B right, both
lap clocks from their own gate frame, gap chart with a cursor; `--audio a|b|none`, `--no-video` for the
report only). It renders with OpenCV (about 40 s); `--renderer hyperframes` gives nicer type but took
about 15 min for a 15 s clip. Tell the pilot the final gap and the sector or moment where most time goes; sector deltas
match `report.md` when both laps have sector splits against the same reference lap.

## When things go wrong

| Symptom | What to do |
|---|---|
| "No parked start found" / "Could not find a repeating lap pattern" | Footage doesn't start parked at the gate, or there are too few laps. Use `--anchor VIDEO:FRAME`. |
| A video shows `armed via motion (no OSD timer found)` | No `mm:ss` timer is on screen, or the OSD font differs from Betaflight's default. Laps still work. Disarm detection then relies on motion only. `motion (OSD timer in a wider layout, ...)`: a wide-spaced timer (other pilots' uploads) was found; `verify` uses it for edits and to overrule motion-guessed disarms. |
| No 3-lap result | Not enough consecutive clean laps. Check `laps.csv` reasons, then `--rank` / the runners-up. |
| HyperFrames render fails | Re-run with `--renderer opencv`, and report the HyperFrames error. |
| `yt-dlp could not download`, or "Only images are available" | Update it (`pip install -U 'yt-dlp[default]'`), check `doctor` for a JavaScript runtime, and check the video is public or unlisted. |
| `verify` says **not verifiable** on an upload | No reference or no 3-lap chain. Re-run with `--readme`/`--track` for the track, or `--anchor <id>:FRAME` on a start-gate crossing. |

How the detection works and which knobs exist (`scripts/fpvlaps/config.py`): see
`references/method.md`. Read it when the results look wrong or the footage is unusual (different
OSD, different frame rate, no parked start).
