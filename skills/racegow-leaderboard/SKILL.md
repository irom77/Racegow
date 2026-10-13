---
name: racegow-leaderboard
description: Look up a pilot's current position on the RaceGOW tiny-whoop race leaderboards (https://www.racegow.com/leaderboards) by their "Unofficial Time", per track. Reads the public Google Sheet the page embeds, computes the rank (the sheet's own Rank column stays "TBD" until the results livestream), and writes a small JSON with rank, of, time and fetched_at that the YouTube upload step uses for the video description. Use whenever someone asks for their RaceGOW rank, position, standing or place, where they are on the leaderboard, or how their submitted time compares, even if they only say "where am I on RaceGOW".
compatibility: Python 3.9+, standard library only. Needs internet access to racegow.com and docs.google.com.
---

# RaceGOW leaderboard position

Default pilot: **papfpv**, Reg# **300** (PAPFPV in the OSD). Reg# is the registration number,
not the rank. `<skill-dir>` means the folder that contains this SKILL.md.

## How the leaderboard works

- The leaderboards page is a Google Site with an embedded Google Sheet. One tab per track
  (`Track1`, `Track2`, ...) and summary tabs (`Rank LB`, `Time LB`, `EMAX LB`, `Velocidrone LB`)
  that say "Coming Soon" until the season ends.
- Columns: `Rank, Reg#, Pilot Name, Unofficial Time, Video Link, ... , Official Time`. `Rank` is
  `TBD` for everyone, so the script ranks by `Unofficial Time` (lower is better).
- Times **under 16 s are hidden** until after the deadline (placeholder rows at the top), so the
  real position may be lower than the computed one. The script sets `hidden_fast_times` when it
  sees that notice.
- Some pilots submit several runs, and some Reg# values are shared by different nicknames.
  `rank`/`of` use each pilot's best time (pilots grouped by nickname); `rank_by_entry` counts
  every listed row.
- `half` is `top` when `rank <= of / 2`, else `bottom` (with an odd number of pilots the middle
  one counts as bottom). `top_percent` is `rank / of` as a percentage.

## Run it

```bash
python3 <skill-dir>/scripts/leaderboard.py                 # papfpv / 300, all track tabs
python3 <skill-dir>/scripts/leaderboard.py --track 2 --out <work>/leaderboard.json
python3 <skill-dir>/scripts/leaderboard.py --pilot "someone" --reg ""   # another pilot, by name only
```

The pilot is matched by Reg# **or** by nickname, ignoring case, spaces and punctuation
(`@PAP_FPV` matches `papfpv`). Ties share a rank (competition ranking: faster pilots + 1).

Output (stdout and `--out`), top-level fields for the latest track the pilot appears on:

```json
{"pilot": "papfpv", "reg": "300", "track": "Track1", "rank": 223, "of": 343, "time": 30.77,
 "half": "bottom", "top_percent": 65.0,
 "fetched_at": "2026-10-13T13:16:08+00:00", "source": "https://www.racegow.com/leaderboards",
 "title": "RaceGOW6 Leaderboards sponsored by HQProp",
 "tracks": {"Track1": {"found": true, "rank": 223, "of": 343, "rank_by_entry": 226,
            "entries": 353, "video": "...", "sheet_row": 237, "hidden_fast_times": true}}}
```

Exit codes: `0` found, `2` pilot not on any track tab, `3` page or sheet layout changed.

## Report back

One line per track, e.g. "Track 1: **223rd of 343 pilots** with 30.770 s, **bottom half** (top 65 %;
226th of 353 entries; times under 16 s are still hidden, so the final position may be lower)."
Always say whether the pilot is in the top or bottom half, and include `fetched_at`.

- **Not found (exit 2):** say so, and list the tracks checked. Don't guess a position. The time
  may not be entered yet; the sheet is updated by hand.
- **Layout changed (exit 3):** say what the script reported, then open the page with a headless
  browser (Playwright) or fetch the sheet CSV by hand to see what moved, and fix the script
  rather than reading numbers off by eye.
- Never write the Reg# into a description as a rank.
