"""YouTube title/description/tags for a highlights short, and the upload. The Google sign-in (token in
~/.config/racegow-youtube/) and the channel check are shared with the racegow-youtube skill: run its
`yt_upload.py auth` once if there is no token yet."""
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from .pick import mmss

REPO_URL = "https://github.com/irom77/Racegow"
YT_SCRIPT = Path(__file__).resolve().parents[3] / "racegow-youtube" / "scripts" / "yt_upload.py"
# Credit for the repo and its AI skills, in every description (the pilot wants the tools recognised).
PROMO = [
    "Made with AI: this Short was found, cut and uploaded by the fpv-highlights agent skill "
    "(runs in Claude Code, Codex or any AI coding agent) from the open-source Racegow repo. It scans every "
    "DVR recording, scores speed, rolls, dives and close passes, skips parked, menu and crash footage, "
    "and picks varied moments.",
    f"Free on GitHub: {REPO_URL}",
    "Also in the repo: fpv-best-laps (best 3 consecutive race laps with a lap-time overlay), "
    "RaceGOW leaderboard lookup and YouTube upload skills.",
]
PLAYLIST = "FPV highlights"     # every highlights Short goes into this playlist on the channel
PLAYLIST_DESC = ("FPV highlight Shorts, cut automatically from raw DVR footage by the fpv-highlights AI agent "
                 f"skill. Free and open source: {REPO_URL}")
SYSTEMS = [(r"^(hot_)?hdz_", "HDZero"), (r"^dji|^DJIG", "DJI"), (r"^avatar|^AvatarG", "Walksnail")]


def _yt():
    spec = importlib.util.spec_from_file_location("yt_upload", YT_SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def flown_date(videos_dir, clips):
    """Date from the folder name (HDZero_12_16_2024, 2024-12-16, 20241216), else the files' dates when
    they are plausible (goggles without a clock write 2023-03-28 or 1970)."""
    name = Path(videos_dir).name
    for pat, order in ((r"(\d{2})[_-](\d{2})[_-](\d{4})", "mdy"), (r"(\d{4})[_-](\d{2})[_-](\d{2})", "ymd"),
                       (r"(20\d{2})(\d{2})(\d{2})", "ymd")):
        m = re.search(pat, name)
        if m:
            a, b, c = m.groups()
            y, mo, d = (c, a, b) if order == "mdy" else (a, b, c)
            try:
                return datetime(int(y), int(mo), int(d)).date().isoformat(), "folder name"
            except ValueError:
                pass
    dates = sorted(datetime.fromtimestamp(Path(p["path"]).stat().st_mtime).date() for p in clips
                   if Path(p["path"]).exists())
    if dates and dates[0].year >= 2015:
        return dates[0].isoformat(), "file dates"
    return None, "unknown"


def build_meta(work, title=None, quad=None, pilot="PAPFPV", place=None, date=None, out=None):
    work = Path(work)
    res = json.loads((work / "picks.json").read_text())
    rj = work / "export" / "render.json"
    if not rj.exists():
        raise SystemExit("render the short first")
    r = json.loads(rj.read_text())
    clips = res["clips"]
    if date == "none":            # folder spans several sessions: leave the date out
        date, date_src = None, "left out"
    else:
        date, date_src = (date, "given") if date else flown_date(res["videos_dir"], clips)
    system = next((s for pat, s in SYSTEMS if re.match(pat, clips[0]["video"], re.I)), None)
    when = datetime.fromisoformat(date).strftime("%b %-d, %Y") if date else ""
    vertical = r["size"][1] > r["size"][0]
    if not title:
        title = " ".join(x for x in ["FPV highlights", f"{place}" if place else "", when] if x) + f" | {pilot}"
    if vertical and r["seconds"] <= 180 and "#shorts" not in title.lower():
        title += " #Shorts"
    lines = [f"{len(clips)} FPV moments, {r['seconds']:.0f} s, picked automatically from "
             f"{res['recordings']} {system + ' ' if system else ''}DVR recordings "
             f"({res['footage_s'] / 60:.0f} min of footage).",
             f"Edited by an AI agent skill, free and open source: {REPO_URL}", ""]
    if date:
        lines.append(f"Flown: {date}" + (f", {place}" if place else ""))
    elif place:
        lines.append(f"Flown at: {place}")
    if quad:
        lines.append(f"{'Quads' if ',' in quad else 'Quad'}: {quad}")
    lines.append(f"Video: {system + ' ' if system else ''}DVR, original audio" +
                 (", music added" if r.get("music") else ""))
    lines.append(f"Pilot: {pilot}")
    lines += ["", "Clips:"] + [f"{mmss(c['at'])[:-2]} {c['video']} @ {mmss(c['start'])[:-2]}" for c in r["clips"]]
    lines += ["", *PROMO, "",
              "#FPV #fpvdrone" + (f" #{system}" if system else "") + (" #Shorts" if vertical else "")]
    tags = ["FPV", "FPV drone", "drone", "freestyle", pilot, "AI video editing", "Claude Code", "AI agent skill",
            "Racegow"] + ([system] if system else []) + \
           [q.strip() for q in (quad or "").split(",") if q.strip()] + (["Shorts"] if vertical else [])
    meta = dict(title=title[:100], description="\n".join(lines), tags=tags, categoryId="17",
                file=r.get("saved") or r["output"], local=r["output"], date=date, date_source=date_src,
                warnings=[] if date or date_src == "left out" else ["date flown unknown: pass --date"])
    if not quad:
        meta["warnings"].append("no quad named: pass --quad (look up the OSD craft name in hardware.csv)")
    old = work / "export" / "youtube.json"
    if old.exists():
        meta["youtube"] = json.loads(old.read_text()).get("youtube")
    out = Path(out) if out else old
    out.write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n")
    print(f"META {out}\n\nTITLE\n{meta['title']}\n\nDESCRIPTION\n{meta['description']}\n\n"
          f"TAGS {', '.join(tags)}\nFILE {meta['file']}")
    for w in meta["warnings"]:
        print(f"WARNING {w}")
    return meta


def find_playlist(yt, title=PLAYLIST):
    req = yt.playlists().list(part="snippet", mine=True, maxResults=50)
    while req is not None:
        resp = req.execute()
        for it in resp.get("items", []):
            if it["snippet"]["title"].strip().lower() == title.lower():
                return it["id"]
        req = yt.playlists().list_next(req, resp)
    return None


def ensure_playlist(yt, title=PLAYLIST, privacy="public"):
    """The playlist's id; created (public, with the repo credit) when the channel has none by that title."""
    pid = find_playlist(yt, title)
    if pid:
        return pid, False
    body = {"snippet": {"title": title, "description": PLAYLIST_DESC}, "status": {"privacyStatus": privacy}}
    return yt.playlists().insert(part="snippet,status", body=body).execute()["id"], True


def playlist_videos(yt, pid):
    ids, req = set(), yt.playlistItems().list(part="contentDetails", playlistId=pid, maxResults=50)
    while req is not None:
        resp = req.execute()
        ids |= {it["contentDetails"]["videoId"] for it in resp.get("items", [])}
        req = yt.playlistItems().list_next(req, resp)
    return ids


def add_to_playlist(video_ids, title=PLAYLIST, yt=None):
    """Add videos to the playlist (created if missing), skipping ones already in it. Returns the playlist URL.
    Needs a token with the full youtube scope: `yt_upload.py auth` (racegow-youtube) asks for it."""
    yt_mod = _yt()
    if yt_mod.PLAYLIST_SCOPE not in yt_mod.token_scopes():
        raise PermissionError("the YouTube token can upload but not edit playlists: sign in again with "
                              f"`python {YT_SCRIPT} auth` (no --client needed), then run "
                              "`fpvhl.py playlist --work <work>`")
    yt = yt or yt_mod.youtube()
    pid, new = ensure_playlist(yt, title)
    have = set() if new else playlist_videos(yt, pid)   # a new playlist can 404 for a few seconds
    for v in video_ids:
        if v in have:
            print(f"  {v} already in playlist {title!r}")
            continue
        yt.playlistItems().insert(part="snippet", body={"snippet": {
            "playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": v}}}).execute()
        print(f"  added {v} to playlist {title!r}")
    url = f"https://www.youtube.com/playlist?list={pid}"
    print(f"PLAYLIST {url}" + ("  (created)" if new else ""))
    return url


def video_id(url):
    m = re.search(r"(?:youtu\.be/|v=|shorts/)([\w-]{11})", url) or re.fullmatch(r"([\w-]{11})", url)
    return m.group(1) if m else None


def playlist(work=None, videos=(), title=PLAYLIST):
    """Add this work's uploaded short (and/or the given video ids/URLs) to the playlist; record it."""
    ids = [video_id(v) for v in videos]
    mp = Path(work) / "export" / "youtube.json" if work else None
    m = json.loads(mp.read_text()) if mp and mp.exists() else {}
    if work:
        if not m.get("youtube"):
            raise SystemExit(f"{work}: not uploaded yet")
        ids.append(video_id(m["youtube"]["url"]))
    if not ids or None in ids:
        raise SystemExit("nothing to add: pass --work (an uploaded short) or --video ID/URL")
    url = add_to_playlist(ids, title)
    if m.get("youtube"):
        m["youtube"]["playlist"] = url
        mp.write_text(json.dumps(m, indent=1, ensure_ascii=False) + "\n")
    return url


def upload(work, privacy="public", expect_channel="@niuk9290", again=False, playlist_title=PLAYLIST):
    work = Path(work)
    mp = work / "export" / "youtube.json"
    if not mp.exists():
        raise SystemExit("run `meta` first (and show the title/description to the pilot)")
    m = json.loads(mp.read_text())
    if m.get("youtube") and not again:
        raise SystemExit(f"already uploaded as {m['youtube']['url']} (pass --again for a second copy)")
    file = next((f for f in (m.get("file"), m.get("local")) if f and Path(f).exists()), None)
    if not file:
        raise SystemExit(f"short not found: {m.get('file')}")
    yt_mod = _yt()
    from googleapiclient.http import MediaFileUpload
    yt = yt_mod.youtube()
    chans = yt_mod.channels(yt)
    want = expect_channel.lower().lstrip("@")
    if not any(want in (c["id"].lower(), c["title"].lower(), c["handle"].lower().lstrip("@")) for c in chans):
        raise SystemExit(f"token uploads to {chans}, not {expect_channel!r}: nothing uploaded")
    body = {"snippet": {"title": m["title"], "description": m["description"], "tags": m.get("tags", []),
                        "categoryId": m.get("categoryId", "17")},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}}
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(file, chunksize=8 * 1024 * 1024, resumable=True))
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"uploaded {status.progress():.0%}", flush=True)
    url = f"https://youtu.be/{resp['id']}"
    print("VIDEO", resp["id"], url, resp["status"]["privacyStatus"])
    entry = dict(url=url, privacy=resp["status"]["privacyStatus"], channel=chans[0],
                 uploaded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), file=file)
    m["youtube"] = entry
    mp.write_text(json.dumps(m, indent=1, ensure_ascii=False) + "\n")
    pj = work / "picks.json"
    res = json.loads(pj.read_text())
    res.setdefault("uploads", []).append(entry)
    pj.write_text(json.dumps(res, indent=1))
    print(f"saved in {mp} and {pj}")
    if playlist_title:
        try:
            entry["playlist"] = add_to_playlist([resp["id"]], playlist_title, yt)
            mp.write_text(json.dumps(m, indent=1, ensure_ascii=False) + "\n")
        except PermissionError as e:
            print(f"WARNING not added to playlist {playlist_title!r}: {e}")
    return url
