---
name: fpv-highlights
description: Cut the most interesting moments of a folder of FPV recordings (freestyle, cruising, park or indoor sessions - not racing) into one short video, by default a vertical YouTube Short of at most 60 seconds, save it outside the recordings folder and upload it to the pilot's YouTube channel. Scores every 0.1 s of every recording for speed, rolls/flips, dives and close passes, drops parked/menu/static/post-flight-STATS footage, and picks varied clips. Use whenever someone wants a highlight reel, a short, a best-moments or montage clip, or "the best bits" from a folder of hdz_*/DJI/Walksnail DVR files that isn't a lap-time race (for best laps use fpv-best-laps).
compatibility: Python 3.9+ with av (PyAV), opencv-python-headless and numpy (scripts/requirements.txt). Upload needs google-api-python-client + google-auth-oauthlib and the racegow-youtube skill's sign-in token.
---

# FPV highlights short

Turns a folder of raw FPV recordings into one short: the best moments, hard-cut, original audio,
vertical 1080x1920 for YouTube Shorts (default max **60 s**), then uploads it. Pilot **PAPFPV**,
channel **@niuk9290**, public by default. `<skill-dir>` = the folder with this SKILL.md. Use the
repo's `.venv/bin/python` (it has PyAV) or install `scripts/requirements.txt`.

**The recordings folder is deleted by hand once the short is published and reviewed on YouTube.**
So nothing the pilot keeps may live in it: the short is copied to
`<recordings parent>/fpv-shorts/<folder name>/` (e.g. `C:\Users\irekr\Videos\fpv-shorts\HDZero_12_16_2024\`,
WSL `/mnt/c/Users/irekr/Videos/fpv-shorts/...`). The tool refuses a `--save-to` inside the recordings
folder. Never write anything into the recordings folder.

## 1. Scan + pick

```bash
python <skill-dir>/scripts/fpvhl.py pick --videos "<folder>" [--length 60] [--clip 5] [--per-video 2]
```

- Scans every recording once (decodes all frames with PyAV; cached in `<work>/scan/`, default work
  `./fpvlaps-work/hl_<folder>`). Measured: ~34 s per 4 min of 720p HEVC on 4 cores; 6 h of footage
  (62 GB, 192 files, read from a Windows drive under WSL) takes roughly 20-30 min with 7 workers.
  Run it in the background and tell the pilot how long.
- Don't use the static `ffmpeg` binary on HDZero `.ts` files: it segfaults on them (7.0.2). PyAV reads them.
- Picks clips greedily by score (speed, roll, dive, parallax = close passes), at most `--per-video`
  per recording, no repeated views, until `--length` is used. `--clip` is the typical clip length
  (clips grow up to 1.6x while the action lasts). Order: best clip first (the hook), then recording order.
- Output: `picks.md` (the clips with times in the recordings + 40 other candidates),
  `sheets/picks.jpg` (one row per clip, 5 decoded frames), `sheets/candidates.jpg`, `picks.json`.

## 2. Review the picks (always, before rendering)

Open `sheets/picks.jpg`. Every row must be **real flight**. Automatically dropped: parked, menus,
static/no signal, black, Betaflight's post-flight STATS screen. Not caught, check for these:

- the quad **carried by hand** before arming (person, hands, walking; no STATS screen yet)
- **simulator / HDMI-in** footage recorded in the goggles (synthetic neon scenes, desktop)
- a clip that **ends in a crash** or tumbling (fine if the pilot wants crashes, otherwise cut it)
- too many clips of the **same place** (e.g. all living room): exclude some to vary it

Fix with `--exclude VIDEO` (whole recording) or `--exclude VIDEO:A-B` (seconds or m:ss in that
recording), and `--include VIDEO:A-B` to force a moment the pilot wants; re-run `pick` (seconds,
scan is cached). `sheets/candidates.jpg` + `picks.md` list the alternatives. If you can't view
images, say so and ask the pilot to look at `sheets/picks.jpg`.

## 3. Render (and save outside the recordings folder)

```bash
python <skill-dir>/scripts/fpvhl.py render --work <work> [--layout fit|crop|wide] [--title "TEXT"] [--music FILE|auto]
```

- `fit` (default): 1080x1920, whole picture full width over a blurred, dimmed copy of itself; the
  OSD stays readable. `crop`: 9:16 crop filling the screen (more immersive, loses the sides and most
  OSD). `wide`: 1920x1080 for a normal video (pass `--length` > 60 at pick time for a longer one).
- `--title` puts text in the band above the picture (none by default). Original audio, 0.3 s fade
  in/out; music only if the pilot asks (`--music auto` = generated track, from fpv-best-laps).
- Writes `<work>/export/short_<folder>_<layout>_<N>s.mp4` and copies it to the fpv-shorts folder
  (`--save-to DIR` elsewhere, `--no-save` to skip; `save --work <work>` copies again later).
- About 1-3 min for a 60 s short. Look at a few frames of the result before uploading.

`run --videos <folder>` does scan + pick + render in one go, for when the pilot skips the review.

## 4. Upload to YouTube

```bash
python <skill-dir>/scripts/fpvhl.py meta --work <work> [--quad "NAME"] [--place "TEXT"] [--date YYYY-MM-DD] [--title "TEXT"]
python <skill-dir>/scripts/fpvhl.py upload --work <work> [--privacy public]
```

- `meta` builds the title (`FPV highlights <place> <date> | PAPFPV #Shorts`), description (what it is,
  date flown, quad, video system, a clip list with each clip's source recording and time, repo link)
  and tags into `<work>/export/youtube.json`. The date comes from the folder name
  (`HDZero_12_16_2024` = 2024-12-16); HDZero goggles without a clock stamp files 2023-03-28, so file
  dates are only used when plausible. A goggles dump folder often holds many sessions (check the
  sheets: summer and winter, different places): then the folder date is only the copy date, so pass
  `--date none` (or the real date if the pilot knows it).
- Every description ends with a **credit block for the repo and its AI skills** (`youtube.PROMO`):
  made with the fpv-highlights agent skill, link to https://github.com/irom77/Racegow, the other
  skills. The pilot wants the repo recognised: keep it, even when the rest of the text is changed.
- `--title` replaces the title when the pilot asks for one (e.g. `--title "FPV highlights 2024 | PAPFPV"`);
  `#Shorts` is appended for a vertical short of 3 min or less.
- Quad: read the craft name from the OSD on the sheets and look it up in the pilot's quad list
  (github irom77/fpv_cli_dumps `hardware.csv`); ask if several quads appear or none is readable.
- **Show the pilot the title, description, channel and privacy and get an OK before `upload`.**
  The upload checks the token's channel is `--expect-channel` (@niuk9290) and records the URL in
  `youtube.json` and `picks.json`. A vertical video of 3 min or less becomes a Short automatically.
- `upload` needs google-api-python-client + google-auth-oauthlib in the same Python as PyAV/OpenCV
  (`.venv/bin/pip install google-api-python-client google-auth-oauthlib`; done in the repo .venv).
- Sign-in is shared with the racegow-youtube skill (token in `~/.config/racegow-youtube/`). If it
  has expired, run that skill's `yt_upload.py auth --client <client_secret.json>` (see its SKILL.md).

## 5. Report

Give the pilot: the YouTube URL and privacy, the saved copy's path (outside the recordings folder),
the clip list (recording + time), how much footage was scanned, what you excluded and why, and that
the recordings folder can be deleted after they've reviewed the short (nothing of ours is in it).

## How it scores

`scripts/fpvhl/scan.py` and `pick.py` docstrings have the details. Per 0.1 s: dense optical flow
on a 160x90 copy of the picture (black bars cropped), fitted with a similarity transform: speed
(translation), roll (rotation), zoom (dive / punch-out) and parallax (flow the fit misses = objects
close to the camera). Each is divided by the session's own 90th percentile, so "interesting" is
relative to the session. Weights in `pick.W`; thresholds `STILL_DIFF`, `OSD_TEXT`, `SAME_VIEW`.
Constant-bitrate DVRs (HDZero) make packet sizes useless as a motion measure, hence the full decode.
