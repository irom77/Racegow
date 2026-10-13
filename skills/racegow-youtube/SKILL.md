---
name: racegow-youtube
description: Upload a verified best-3-consecutive-laps clip (from the fpv-best-laps skill) to the pilot's YouTube channel, with the title, description and tags built from the run - track, 3-lap time and splits, pilot, current RaceGOW leaderboard rank, quad, date flown, sponsor, deadline and the organiser's demo flythrough link - then record the video URL in result.json and the track README. Use whenever someone wants to upload, post, publish or share a best-laps / RaceGOW / whoop race clip on YouTube, or asks for a YouTube title or description for one.
compatibility: Python 3.9+. Building the description needs only the standard library; uploading needs google-api-python-client and google-auth-oauthlib (scripts/requirements.txt), or `uv run --with`. Needs a Google Cloud OAuth desktop client with YouTube Data API v3 enabled.
---

# Upload a best-laps clip to YouTube

Pilot **PAPFPV**. `<skill-dir>` is the folder with this SKILL.md, `<work>` the fpv-best-laps work
folder (has `result.json` and `export/render_rank<N>.json`). Only upload a clip whose laps were
verified against the demo flythrough (see the fpv-best-laps skill).

Run the script with the Google libraries available, for example:

```bash
YT="uv run -q --no-project --with google-api-python-client --with google-auth-oauthlib python <skill-dir>/scripts/yt_upload.py"
```

(or `pip install -r <skill-dir>/scripts/requirements.txt` into a venv). `meta` and `record` work
with plain `python3`.

## 1. Sign in (once per machine)

The token is in `~/.config/racegow-youtube/token.json` (mode 600, never in a repo) and refreshes by
itself. If it's missing or revoked:

```bash
$YT auth --client /path/to/client_secret_XXXX.json
```

It prints `AUTH_URL ...`. There's no browser on WSL, so give the pilot that URL to open. Google
redirects to `http://localhost:8765`, which the script is listening on. Then the pilot picks the
**channel** to upload to at the Google sign-in. Setup in the Google Cloud project, once:
enable **YouTube Data API v3**, create an OAuth client of type **Desktop app**, and while the app is
in testing mode add the pilot's Google account as a **test user**. Scopes: `youtube.upload` and
`youtube.readonly` (to read the channel name).

## 2. Build the title and description

```bash
python3 <skill-dir>/scripts/yt_upload.py meta --work <work> --rank 1
```

It writes `<work>/export/youtube_rank1.json` and prints the title, description, tags and clip.
Where each part comes from:

| Part | Source (override) |
|---|---|
| Time and lap splits, clip | `result.json` best rank N, `export/render_rankN.json` (`--rank`) |
| RaceGOW and track number | folder names such as `RaceeGow6/Track2/1st` (`--race`, `--track`) |
| Demo link + flythrough start | track README: `**Demo video:** <url> ("title")`, `**Flythrough starts at:** 1:00` (`--readme`) |
| Sponsor/designer sentence, deadline | the demo video's description, read with `yt-dlp` (or `uvx yt-dlp`): "RaceGOW6 Track2 is sponsored by ...", "DEADLINE = ..." (`--about-line`, `--deadline`; `--offline` skips it) |
| Sponsor, designer (fallback, tags) | the demo title in the README, "sponsored by X and designed by Y" (`--sponsor`, `--designer`) |
| Leaderboard rank | runs the **racegow-leaderboard** skill now (`--leaderboard file.json`, `--no-rank`) |
| Quad, video system | `--quad` (default Air65, the OSD craft name); system from file names, `hdz_` = HDZero (`--video-system`) |
| Date flown | container `creation_time`, else the file time (`--date`) |

Title format: `RaceGOW6 Track 2 | 41.43s best 3 consecutive laps | PAPFPV`. Category 17 (Sports),
not made for kids. The rank is per track: if the track being uploaded isn't on the leaderboard yet,
the description gives the rank on the latest track that is, and says which track. The
description never says top or bottom half; that's only for the leaderboard report. The Reg#
(300) is never a rank.

Fix every `WARNING` line (pass the missing flag) before going on. If the deadline is missing, read
the demo description yourself (`uvx yt-dlp --skip-download --print description <demo url>`).

## 3. Get approval, then upload

1. **Show the pilot the full title, description and tags** and get an OK. Edit the JSON if they
   want wording changes.
2. **Confirm the channel:** run `$YT channel` and ask the pilot whether that's the channel they
   want. The first uploads went to **papfpv / @niuk9290** (`UCJeJajoMrXyvZQP2-tKLT8A`), not
   youtube.com/irom77. If they want another channel, run `auth` again and pick it at sign-in.
3. **Ask for privacy:** `private`, `unlisted` or `public`. It's the pilot's call every time (the
   first uploads were public). Don't assume.

```bash
$YT upload --meta <work>/export/youtube_rank1.json --privacy public --expect-channel @niuk9290
```

`--expect-channel` takes the confirmed id, title or @handle. The upload is refused if the token
points to a different channel, or if this meta JSON was already uploaded (`--again` to override).
The upload is resumable, in 8 MB chunks, with progress.

## 4. Record the URL

`upload` saves the URL by itself, in:

- the meta JSON (`youtube`),
- `<work>/result.json` (`uploads`: rank, video, total, url, privacy, channel, uploaded_at),
- the track README's results table: the YouTube column of the row with this video and total. If
  there's no such row, it says so; add the row by hand (batch, time and splits, video and time
  range, clip, YouTube).

For a video uploaded some other way: `python3 <skill-dir>/scripts/yt_upload.py record --meta ... --url ...`.

Report the URL, privacy and channel to the pilot.
