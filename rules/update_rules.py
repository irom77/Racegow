#!/usr/bin/env python3
"""Save the current RaceGOW season's rules from racegow.com into rules/RaceGOW<N>/.

The rules live in Google Docs embedded on https://www.racegow.com/home (labelled e.g.
"RaceGOW2 - Scoring"; the organiser reuses the same docs every season and edits them in place).
This script finds the season number on the page (highest "RaceGOW<N>"), exports each embedded doc
as plain text and writes it to rules/RaceGOW<N>/<name>.md. A file is rewritten only when the text
changed, so `git diff rules/` shows exactly what the organiser edited. sources.json records each
doc's URL and when its text last changed (nothing is rewritten when nothing changed).

  python3 rules/update_rules.py            # update the current season's folder
  python3 rules/update_rules.py --check    # only report; exit 1 if anything is new or changed

Standard library only. Exit codes: 0 up to date / updated, 1 changes found with --check,
3 page layout changed (no season number or no embedded docs found).
"""
import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PAGE = "https://www.racegow.com/home"
DOC = "https://docs.google.com/document/d/{id}"
UA = {"User-Agent": "Mozilla/5.0 (racegow rules updater)"}
ROOT = Path(__file__).resolve().parent


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def find_docs(html):
    """[(label, doc_id)] for each embedded Google Doc, in page order, without duplicates."""
    found = re.findall(r'aria-label="Document, ([^"]+)"[^>]*?data-src="https://docs\.google\.com/'
                       r'document/d/([\w-]{20,})/', html)
    seen, docs = set(), []
    for label, doc_id in found:
        if doc_id not in seen:
            seen.add(doc_id)
            docs.append((label.strip(), doc_id))
    return docs


def slug(label):
    """'RaceGOW2 - Micro Tiers' -> 'micro-tiers' (the season prefix in labels is stale)."""
    name = label.split(" - ", 1)[-1]
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "doc"


def doc_text(doc_id):
    text = get(DOC.format(id=doc_id) + "/export?format=txt").replace("\r", "").lstrip("﻿")
    lines = [l.rstrip() for l in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="report only, write nothing")
    a = ap.parse_args()

    html = get(PAGE)
    seasons = [int(n) for n in re.findall(r"RaceGOW\s?(\d+)", html)]
    docs = find_docs(html)
    if not seasons or not docs:
        print(f"layout changed: season numbers {sorted(set(seasons))}, docs {docs}", file=sys.stderr)
        return 3
    season = f"RaceGOW{max(seasons)}"
    folder = ROOT / season
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta_path = folder / "sources.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {"season": season, "docs": {}}

    changes = []
    for label, doc_id in docs:
        name = slug(label) + ".md"
        body = doc_text(doc_id)
        url = DOC.format(id=doc_id)
        content = f"<!-- {label}: {url} (exported by rules/update_rules.py) -->\n\n{body}"
        path = folder / name
        old = path.read_text() if path.exists() else None
        status = "new" if old is None else ("changed" if old != content else "unchanged")
        print(f"{season}/{name}: {status}  ({label})")
        entry = meta["docs"].setdefault(name, {"label": label, "url": url})
        if status != "unchanged":
            entry.update(label=label, url=url)
            changes.append(name)
            entry["changed_at"] = now
            if not a.check:
                folder.mkdir(exist_ok=True)
                path.write_text(content)
    gone = sorted(set(meta["docs"]) - {slug(l) + ".md" for l, _ in docs})
    for name in gone:
        print(f"{season}/{name}: no longer on the page (file kept)")

    if a.check:
        return 1 if changes else 0
    if changes:
        meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"{len(changes)} file(s) written to rules/{season}/" if changes else "rules are up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
