# RaceGOW rules

Copies of the official RaceGOW rules, one folder per season. The originals are Google Docs embedded
on <https://www.racegow.com/home>. The organiser edits the same docs every season, so they are
labelled "RaceGOW2 - ..." even when they hold the current season's rules.

```
rules/
├── update_rules.py      fetches the current season's docs into RaceGOW<N>/
└── RaceGOW6/
    ├── scoring.md       general rules, code of ethics, season scoring (Rank LB, Time LB, Micro Tier)
    ├── micro-tiers.md   micro tier brackets and Bonus Tier cash prizes
    ├── classes.md       track build, drone classes (Open, EMAX, Velocidrone), common questions
    └── sources.json     each doc's URL and when its text last changed
```

## Keep them up to date

```bash
python3 rules/update_rules.py            # write changes into the current season's folder
python3 rules/update_rules.py --check    # report only; exit 1 if a doc is new or changed
git diff rules/                          # see exactly what the organiser changed
```

The script works out the season from the highest "RaceGOW<N>" on the home page. Files are rewritten
only when the text changes, so a clean `git status` means the rules haven't changed since the last
commit. Run it at the start of each track, or whenever someone asks about the rules, and commit any
changes.

## A new season

When racegow.com moves on to RaceGOW7, the script creates `rules/RaceGOW7/` on its next run. Earlier
folders are never touched again, so each one keeps the rules as they were at the end of that season.

## Not in the rules

The rules never mention a top or bottom half. The leaderboard skill's `half` is its own measure,
counted among pilots who submitted on that track (see
[`skills/racegow-leaderboard/SKILL.md`](../skills/racegow-leaderboard/SKILL.md)).
