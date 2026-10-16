---
name: racegow-leaderboard
description: Look up a pilot's current position on the RaceGOW tiny-whoop race leaderboards (https://www.racegow.com/leaderboards) per track. Reads the public Google Sheet the page embeds and reports the official result (Rank, Official Time, Micro Tier) once a track's results are published, otherwise a rank computed from "Unofficial Time" (while the sheet's Rank column says "TBD"). Writes a small JSON with status, rank, of, time, tier and fetched_at that the YouTube upload step uses for the video description. Use whenever someone asks for their RaceGOW rank, position, standing or place, where they are on the leaderboard, or how their submitted time compares, even if they only say "where am I on RaceGOW".
compatibility: Python 3.9+, standard library only. Needs internet access to racegow.com and docs.google.com.
---

# RaceGOW leaderboard position

Default pilot: **papfpv**, Reg# **300** (PAPFPV in the OSD). Reg# is the registration number,
not the rank. `<skill-dir>` means the folder that contains this SKILL.md.

## How the leaderboard works

- The leaderboards page is a Google Site with an embedded Google Sheet. One tab per track
  (`Track1`, `Track2`, ...) and summary tabs (`Rank LB`, `Time LB`, `EMAX LB`, `Velocidrone LB`)
  that say "Coming Soon" until the season ends.
- Columns: `Rank, Micro Tier for T2, Reg#, Pilot Name, Official Time, Unofficial Time, Video Link, ...`
  (order may vary; the script reads them by name).
- **Rule:** the result is official only when the pilot's own row has a numeric `Rank` **and** an
  `Official Time`. Otherwise (Rank `TBD` or blank, no Official Time column or value, or a numbered
  Rank with no official time behind it) the script ranks by `Unofficial Time`.
- **Before results** `Rank` is `TBD`, so the script ranks by `Unofficial Time` (lower is better),
  `status: "unofficial"`. The fastest times are hidden until after the deadline (placeholder rows
  at the top), so the real position may be lower; `hidden_fast_times` is set when the notice is there.
- **After results** (e.g. Track 1 by 2026-10-16) the sheet fills `Rank`, `Official Time` and
  `Micro Tier ...` per entry. The script then reports the sheet's own rank, `status: "official"`,
  with `official_time`, `tier` and `hidden_top` (the top places still shown as placeholders until
  the results livestream; they count in the field). `of` is the highest Rank that has an Official
  Time; entries listed after it have no official time. The computed figures stay under `unofficial`.
- Some pilots submit several runs, and some Reg# values are shared by different nicknames.
  `rank`/`of` use each pilot's best time (pilots grouped by nickname); `rank_by_entry` counts
  every listed row.
- The official rules never define a top or bottom half; it is this skill's own measure. It always
  counts **pilots who submitted on that track** (`of`), never everyone registered: the season tab
  `Rank LB` lists all registered pilots (697 by Track 1) and gives 10000 for every track not flown.
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

Output (stdout and `--out`), top-level fields for the latest track the pilot appears on
(`time` is the official time once published):

```json
{"pilot": "papfpv", "reg": "300", "track": "Track1", "status": "official", "rank": 257, "of": 384,
 "time": 30.617, "half": "bottom", "top_percent": 66.9, "tier": 19,
 "fetched_at": "2026-10-16T12:35:18+00:00", "source": "https://www.racegow.com/leaderboards",
 "title": "RaceGOW6 Leaderboards sponsored by HQProp",
 "tracks": {"Track1": {"found": true, "status": "official", "rank": 257, "of": 384,
            "time": 30.77, "official_time": 30.617, "tier": 19, "tier_label": "Micro Tier for T2",
            "hidden_top": 25, "unofficial": {"rank": 238, "of": 363, "rank_by_entry": 238},
            "entries": 363, "video": "...", "sheet_row": 258, "hidden_fast_times": false}}}
```

Exit codes: `0` found, `2` pilot not on any track tab, `3` page or sheet layout changed.

## Rules

The official rules are saved in the repo under `rules/RaceGOW<N>/` (`scoring.md`, `micro-tiers.md`,
`classes.md`; from this skill folder that's `<skill-dir>/../../rules/`). For a question about
scoring, tiers or prizes, first run `python3 <skill-dir>/../../rules/update_rules.py`, then answer
from those files and quote them. If the script wrote changes, tell the user what changed
(`git diff rules/`) and offer to commit. Also run it with `--check` on each leaderboard lookup, and
mention it if the rules changed.

## Report back

One line per track. Official: "Track 1 (official): **257th of 384** with 30.617 s official
(30.770 s submitted), Micro Tier 19, **bottom half** (top 67 %; the top 25 are revealed at the
results livestream)." Unofficial: "Track 1: **223rd of 343 pilots** with 30.770 s, **bottom half**
(top 65 %; 226th of 353 entries; the fastest times are still hidden, so the final position may be
lower)." Always say official or unofficial.
Always say whether the pilot is in the top or bottom half, and include `fetched_at`.

- **Not found (exit 2):** say so, and list the tracks checked. Don't guess a position. The time
  may not be entered yet; the sheet is updated by hand.
- **Layout changed (exit 3):** say what the script reported, then open the page with a headless
  browser (Playwright) or fetch the sheet CSV by hand to see what moved, and fix the script
  rather than reading numbers off by eye.
- Never write the Reg# into a description as a rank.
