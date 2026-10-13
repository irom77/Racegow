#!/usr/bin/env python3
"""Find a pilot's position on the RaceGOW leaderboards by "Unofficial Time".

The page https://www.racegow.com/leaderboards (a Google Site) embeds a public Google Sheet, one
tab per track ("Track1", "Track2", ...) plus summary tabs. The sheet's "Rank" column stays "TBD"
until the results livestream, so the position is computed here: sort every entry with a valid
Unofficial Time and count how many are strictly faster.

Standard library only. Exit codes: 0 found, 2 pilot not found, 3 page/sheet layout changed.
"""
import argparse
import csv
import io
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone

PAGE = "https://www.racegow.com/leaderboards"
SHEET = "https://docs.google.com/spreadsheets/d/{id}"
UA = {"User-Agent": "Mozilla/5.0 (racegow-leaderboard skill)"}
TIME_COL, PILOT_COL, REG_COL = "Unofficial Time", "Pilot Name", "Reg#"


class LayoutChanged(Exception):
    pass


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def find_sheet_id(page_html):
    """The leaderboard iframe: data-src=".../spreadsheets/d/<id>/htmlembed"."""
    ids = re.findall(r"docs\.google\.com/spreadsheets/d/([\w-]{20,})/htmlembed", page_html)
    if not ids:
        raise LayoutChanged(f"no embedded Google Sheet found on {PAGE}")
    return ids[0]


def sheet_title(page_html):
    """The iframe's label, e.g. "RaceGOW6 Leaderboards sponsored by HQProp" (None if absent)."""
    m = re.search(r'aria-label="Spreadsheet, ([^"]+)"', page_html)
    return m.group(1).strip() if m else None


def list_tabs(sheet_id):
    """[(name, gid)] in sheet order, read from the htmlembed page's tab list."""
    html = get(SHEET.format(id=sheet_id) + "/htmlembed")
    tabs = re.findall(r'\{name: "([^"]*)", pageUrl: "[^"]*", gid: "(\d+)"', html)
    if not tabs:
        raise LayoutChanged("could not read the sheet's tab list")
    return tabs


def read_tab(sheet_id, gid):
    text = get(SHEET.format(id=sheet_id) + f"/export?format=csv&gid={gid}")
    return list(csv.DictReader(io.StringIO(text)))


def norm(name):
    """Case/punctuation-insensitive nickname key: ' @PAP_FPV ' -> 'papfpv'."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def parse_time(s):
    try:
        t = float(s.strip())
    except (ValueError, AttributeError):
        return None
    return t if 0 < t < 600 else None  # drop typos such as 23232


def rank_track(rows, pilot, reg):
    """Position of the pilot's best entry. None if the pilot has no timed entry on this tab."""
    if rows and not {TIME_COL, PILOT_COL, REG_COL} <= set(rows[0]):
        raise LayoutChanged(f"columns changed: {list(rows[0])}")
    entries = []
    for i, r in enumerate(rows):
        t = parse_time(r.get(TIME_COL, ""))
        if t is not None:
            entries.append({"row": i + 2, "time": t, "pilot": r[PILOT_COL].strip(),
                            "reg": r[REG_COL].strip(), "video": r.get("Video Link", "").strip()})
    if not entries:
        return None

    def mine(e):
        if reg and e["reg"] == reg:
            return True
        return bool(pilot) and norm(e["pilot"]) == norm(pilot)

    own = [e for e in entries if mine(e)]
    if not own:
        return {"found": False, "entries": len(entries)}
    best = min(own, key=lambda e: e["time"])

    # Best time per pilot (same nickname = same pilot; some pilots submit several runs).
    per_pilot = {}
    for e in entries:
        k = norm(e["pilot"]) or f"reg{e['reg']}"
        per_pilot[k] = min(per_pilot.get(k, e["time"]), e["time"])
    faster_pilots = sum(1 for k, t in per_pilot.items() if t < best["time"] and k != norm(best["pilot"]))

    # The organisers hold back the fastest times ("if your time is under 16 seconds ... not
    # listed until after the deadline"), so the real position can be lower than computed.
    hidden = any("not be listed" in str(v).lower() for r in rows[:15] for v in r.values())
    rank, of = faster_pilots + 1, len(per_pilot)
    return {
        "found": True,
        "pilot": best["pilot"], "reg": best["reg"], "time": best["time"],
        "video": best["video"], "sheet_row": best["row"],
        "rank": rank, "of": of,
        # Top half: rank in the first of/2 places (with an odd count the middle pilot is bottom).
        "half": "top" if rank <= of / 2 else "bottom",
        "top_percent": round(100 * rank / of, 1),  # e.g. 65.0 = within the top 65 %
        "rank_by_entry": sum(1 for e in entries if e["time"] < best["time"]) + 1,
        "entries": len(entries),
        "own_entries": [{"time": e["time"], "row": e["row"]} for e in own],
        "hidden_fast_times": hidden,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pilot", default="papfpv", help="pilot nickname (case-insensitive)")
    ap.add_argument("--reg", default="300", help="registration number (Reg#); '' to match by name only")
    ap.add_argument("--track", help="only this tab, e.g. Track1 or 1")
    ap.add_argument("--sheet", help="Google Sheet id (skip reading the leaderboards page)")
    ap.add_argument("--out", help="write the JSON here as well as to stdout")
    a = ap.parse_args()

    try:
        page = None if a.sheet else get(PAGE)
        sheet_id = a.sheet or find_sheet_id(page)
        tabs = list_tabs(sheet_id)
        track_tabs = [(n, g) for n, g in tabs if re.fullmatch(r"track\s*\d+", n.strip(), re.I)]
        if a.track:
            want = norm(a.track if not a.track.isdigit() else f"track{a.track}")
            track_tabs = [(n, g) for n, g in track_tabs if norm(n) == want]
            if not track_tabs:
                raise LayoutChanged(f"no tab {a.track!r}; tabs: {[n for n, _ in tabs]}")
        tracks = {}
        for name, gid in track_tabs:
            res = rank_track(read_tab(sheet_id, gid), a.pilot, a.reg)
            tracks[name] = res if res is not None else {"found": False, "entries": 0,
                                                         "note": "no times published yet"}
    except LayoutChanged as e:
        print(json.dumps({"error": "layout_changed", "detail": str(e), "source": PAGE}, indent=2))
        return 3

    found = {n: t for n, t in tracks.items() if t.get("found")}
    out = {
        "pilot": a.pilot, "reg": a.reg or None,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": PAGE, "sheet": SHEET.format(id=sheet_id),
        "title": sheet_title(page) if page else None,
        "tabs": [n for n, _ in tabs],
        "tracks": tracks,
    }
    if found:  # latest track the pilot appears on, for the upload skill's description
        latest = max(found, key=lambda n: int(re.sub(r"\D", "", n)))
        out.update(track=latest, rank=found[latest]["rank"], of=found[latest]["of"],
                   time=found[latest]["time"], half=found[latest]["half"],
                   top_percent=found[latest]["top_percent"])
    text = json.dumps(out, indent=2)
    print(text)
    if a.out:
        with open(a.out, "w") as f:
            f.write(text + "\n")
    return 0 if found else 2


if __name__ == "__main__":
    sys.exit(main())
