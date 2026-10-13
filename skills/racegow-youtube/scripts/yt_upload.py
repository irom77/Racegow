#!/usr/bin/env python3
"""Upload a verified best-3-laps clip to YouTube with a title and description built from the run.

  yt_upload.py auth    --client CLIENT_SECRET.json      # one-time sign-in, saves the token
  yt_upload.py channel                                  # which channel the token uploads to
  yt_upload.py meta    --work WORK [--rank 1] ...       # build title/description/tags -> JSON
  yt_upload.py upload  --meta META.json --privacy public --expect-channel @handle
  yt_upload.py record  --meta META.json --url https://youtu.be/ID   # save a URL by hand

`meta` and `record` need only the standard library. `auth`, `channel` and `upload` need
google-api-python-client and google-auth-oauthlib (see requirements.txt).
The token lives in ~/.config/racegow-youtube/token.json (mode 600), never in a repository.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly"]
CONFIG = Path.home() / ".config" / "racegow-youtube"
TOKEN = CONFIG / "token.json"
AUTH_PORT = 8765

HOME_URL = "https://www.racegow.com/home"
LEADERBOARD_URL = "https://www.racegow.com/leaderboards"
DISCORD_URL = "https://discord.gg/zKTZZty9d9"
REPO_URL = "https://github.com/irom77/Racegow"
LEADERBOARD_SCRIPT = Path(__file__).resolve().parents[2] / "racegow-leaderboard" / "scripts" / "leaderboard.py"

VIDEO_SYSTEMS = [(r"^hdz_", "HDZero"), (r"^dji|^DJIG", "DJI"), (r"^avatar|^AvatarG", "Walksnail")]


# ---------------------------------------------------------------- run data (result.json etc.)

def load_run(work, rank):
    """Best result number `rank` from fpv-best-laps' result.json, plus the rendered clip."""
    result = json.loads((work / "result.json").read_text())
    best = result.get("best") or []
    if not 1 <= rank <= len(best):
        sys.exit(f"{work}/result.json has {len(best)} ranked results, no rank {rank}")
    b = best[rank - 1]
    render = work / "export" / f"render_rank{rank}.json"
    clip = None
    if render.exists():
        out = json.loads(render.read_text())["output"]
        clip = next((p for p in (Path(out), work.parent.parent / out, work / "export" / Path(out).name)
                     if p.exists()), None)
    src = next((v["path"] for v in result.get("videos", []) if v["name"] == b["video"]), None)
    src = next((p for p in (Path(src), work.parent.parent / src) if p.exists()), None) if src else None
    return result, b, clip, src


def flown_date(src):
    """creation_time from the container, else the file time. Goggles without a clock write
    implausible dates, so anything before 2015 is ignored."""
    if not src:
        return None, "unknown"
    ffprobe = shutil.which("ffprobe") or str(Path.home() / ".local/bin/ffprobe")
    try:
        out = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format_tags=creation_time",
                              "-of", "json", str(src)], capture_output=True, text=True, timeout=30)
        ct = json.loads(out.stdout).get("format", {}).get("tags", {}).get("creation_time")
        if ct and ct[:4] >= "2015":
            return ct[:10], "creation_time"
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    d = datetime.fromtimestamp(Path(src).resolve().stat().st_mtime).date()
    return (d.isoformat(), "file time") if d.year >= 2015 else (None, "unknown")


def find_readme(result, src):
    """Track folder README: next to the batch folder or one level up (Track2/1st -> Track2/)."""
    dirs = []
    if src:
        dirs.append(Path(src).resolve().parent)
    if result.get("videos_dir"):
        dirs.append(Path(result["videos_dir"]).resolve())
    for d in dirs:
        for c in (d / "README.md", d.parent / "README.md"):
            if c.exists():
                return c
    return None


def parse_readme(path):
    """Demo URL, its quoted title and the flythrough start, from the track README convention:
    **Demo video:** <url> ("title")   and   **Flythrough starts at:** 1:00"""
    info = {}
    if not path:
        return info
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"\*\*Demo video:\*\*\s*(\S+)(?:\s*\(\"([^\"]+)\")?", text)
    if m:
        info["demo"] = m.group(1)
        info["demo_title"] = " ".join(m.group(2).split()) if m.group(2) else None  # may wrap lines
    m = re.search(r"\*\*Flythrough starts at:\*\*\s*(\d+:\d{2}(?::\d{2})?)", text)
    if m:
        info["flythrough"] = m.group(1)
    t = info.get("demo_title") or ""
    m = re.search(r"sponsored by (.+?)(?: and | with |,|$)", t, re.I)
    if m:
        info["sponsor"] = m.group(1).strip()
    m = re.search(r"(?:designed|inspired) by (.+?)(?:,|$)", t, re.I)
    if m:
        info["designer"] = m.group(1).strip()
    return info


def demo_details(url):
    """Deadline and the sponsor sentence from the organiser's demo video description, e.g.
    "RaceGOW6 Track2 DEADLINE = Sunday, October 25th at 11:59pm PST" and
    "RaceGOW6 Track2 is sponsored by BetaFPV and the design is inspired by Sabj". Uses yt-dlp."""
    cmd = ([shutil.which("yt-dlp")] if shutil.which("yt-dlp") else
           [shutil.which("uvx") or str(Path.home() / ".local/bin/uvx"), "-q", "yt-dlp"])
    try:
        out = subprocess.run(cmd + ["--skip-download", "--print", "description", url],
                             capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    info = {}
    m = re.search(r"DEADLINE\s*[=:]\s*(.+)", out.stdout, re.I)
    if m:
        info["deadline"] = m.group(1).strip().rstrip(".")
    m = re.search(r"^(RaceGOW\s*\d+\s+Track\s*\d+\s+is sponsored by .+?)\.?\s*$", out.stdout, re.I | re.M)
    if m:
        info["about"] = re.sub(r"Track\s*(\d+)", r"Track \1", m.group(1)) + "."
    return info


def numbers_from(*texts):
    """RaceGOW season and track number from folder names such as RaceeGow6/Track2."""
    race = track = None
    for t in filter(None, map(str, texts)):
        race = race or (m := re.search(r"rac\w*?gow\s*(\d+)", t, re.I)) and m.group(1)
        track = track or (m := re.search(r"track\s*(\d+)", t, re.I)) and m.group(1)
    return race, track


def seconds(ts):
    s = 0
    for part in ts.split(":"):
        s = s * 60 + int(part)
    return s


def leaderboard(path):
    """The racegow-leaderboard JSON: from a file, or by running the sibling skill."""
    if path:
        return json.loads(Path(path).read_text())
    if not LEADERBOARD_SCRIPT.exists():
        return None
    out = subprocess.run([sys.executable, "-I", str(LEADERBOARD_SCRIPT)], capture_output=True, text=True,
                         timeout=120)
    try:
        return json.loads(out.stdout)
    except ValueError:
        return None


def ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


# ---------------------------------------------------------------- meta

def build_meta(a):
    work = Path(a.work).resolve()
    result, best, clip, src = load_run(work, a.rank)
    readme = Path(a.readme).resolve() if a.readme else find_readme(result, src)
    info = parse_readme(readme)
    race, track = numbers_from(readme, result.get("videos_dir"), src, work.name)
    race, track = a.race or race, a.track or track
    sponsor, designer = a.sponsor or info.get("sponsor"), a.designer or info.get("designer")
    demo = {} if a.offline or not info.get("demo") else demo_details(info["demo"])
    deadline = a.deadline or demo.get("deadline")
    about_line = a.about_line or (None if (a.sponsor or a.designer) else demo.get("about"))
    flown, flown_src = (a.date, "--date") if a.date else flown_date(src)
    vsys = a.video_system or next((n for p, n in VIDEO_SYSTEMS if re.match(p, best["video"], re.I)), None)
    lb = None if a.no_rank else leaderboard(a.leaderboard)

    warnings = []
    if not (race and track):
        warnings.append("RaceGOW/track number not found: pass --race and --track")
        race, track = race or "?", track or "?"
    if not clip:
        warnings.append(f"no rendered clip for rank {a.rank}: run fpvlaps.py render --rank {a.rank} first")
    if not readme:
        warnings.append("no track README found (pass --readme): no demo link in the description")

    total = f"{best['total']:.2f}"
    laps = [f"{l['time']:.2f}" for l in best["laps"]]
    name = f"RaceGOW{race} Track {track}"
    title = f"{name} | {total}s best {len(laps)} consecutive laps | {a.pilot}"

    lines = [f"{name}: best {len(laps)} consecutive laps in {total} s",
             " · ".join(f"Lap {i}: {t} s" for i, t in enumerate(laps, 1)), ""]
    pilot = f"Pilot: {a.pilot}"
    if lb and lb.get("rank"):
        when = (lb.get("fetched_at") or "")[:10]
        tnum = re.sub(r"\D", "", lb.get("track", "")) or "?"
        pilot += (f" · current RaceGOW{race} Track {tnum} rank: {ordinal(lb['rank'])} of {lb['of']}"
                  f" (unofficial times, {when})")  # no top/bottom half here: that's for the report only
    elif not a.no_rank:
        warnings.append("leaderboard position not found: description has no rank (or pass --leaderboard)")
    lines.append(pilot)
    quad = " · ".join(filter(None, [a.quad, f"{vsys} DVR" if vsys else None]))
    lines.append(f"Quad: {quad}" + (f", flown {flown}" if flown else ""))
    if not flown:
        warnings.append("date flown unknown: pass --date YYYY-MM-DD")

    lines += ["", "About the race"]
    if about_line:
        lines.append(about_line)
    elif sponsor or designer:
        parts = [f"sponsored by {sponsor}" if sponsor else None, f"designed by {designer}" if designer else None]
        lines.append(f"{name} is {' and '.join(filter(None, parts))}.")
    else:
        warnings.append("no sponsor/designer: pass --sponsor/--designer or --about-line")
    if deadline:
        lines.append(f"Track {track} deadline: {deadline}.")
    else:
        warnings.append("no deadline (not in the demo description, or --offline): pass --deadline")
    if info.get("demo"):
        demo = info["demo"]
        if info.get("flythrough"):
            demo += f"{'&' if '?' in demo else '?'}t={seconds(info['flythrough'])}s"
        lines.append(f"Official Track {track} demo and flythrough: {demo}")
    lines.append(f"RaceGOW: {HOME_URL}")
    lb_title = (lb or {}).get("title") or f"RaceGOW{race} leaderboards"
    m = re.match(r"(.*?Leaderboards?)\s+(sponsored by .+)", lb_title, re.I)
    lines.append(f"{m.group(1)} ({m.group(2)}): {LEADERBOARD_URL}" if m else f"{lb_title}: {LEADERBOARD_URL}")
    lines.append(f"RaceGOW Discord: {DISCORD_URL}")
    lines += ["", "Laps timed frame by frame from the DVR with Racegow, the open-source best-lap finder:",
              REPO_URL, "", "Good luck and happy whooping!", "#RaceGOW #tinywhoop #fpv"]

    tags = ["RaceGOW", f"RaceGOW{race}", "tiny whoop", "whoop racing", "FPV", a.quad, vsys, a.pilot, sponsor]
    return {
        "title": title,
        "description": "\n".join(lines),
        "tags": [t for t in dict.fromkeys(tags) if t],
        "categoryId": "17",  # Sports
        "file": str(clip.resolve()) if clip else None,
        "context": {
            "work": str(work), "rank": a.rank, "video": best["video"], "total": best["total"],
            "readme": str(readme) if readme else None, "flown": flown, "flown_source": flown_src,
            "leaderboard": {k: (lb or {}).get(k) for k in ("track", "rank", "of", "half", "fetched_at")},
        },
        "warnings": warnings,
    }


# ---------------------------------------------------------------- YouTube API

def youtube():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        sys.exit("needs google-api-python-client and google-auth-oauthlib (see requirements.txt)")
    if not TOKEN.exists():
        sys.exit(f"no token at {TOKEN}: run `yt_upload.py auth --client CLIENT_SECRET.json` first")
    c = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not c.valid and c.refresh_token:
        c.refresh(Request())
        TOKEN.write_text(c.to_json())
        TOKEN.chmod(0o600)
    return build("youtube", "v3", credentials=c)


def channels(yt):
    items = yt.channels().list(part="snippet", mine=True).execute().get("items", [])
    return [{"id": i["id"], "title": i["snippet"]["title"], "handle": i["snippet"].get("customUrl", "")}
            for i in items]


def cmd_auth(a):
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(a.client, SCOPES)
    # No browser on WSL: print the consent URL and wait for the redirect on localhost.
    c = flow.run_local_server(port=AUTH_PORT, open_browser=False, prompt="consent",
                              authorization_prompt_message="Open this URL to sign in:\nAUTH_URL {url}",
                              success_message="Done. You can close this tab.")
    CONFIG.mkdir(parents=True, exist_ok=True)
    TOKEN.write_text(c.to_json())
    TOKEN.chmod(0o600)
    print(json.dumps(channels(youtube()), indent=2))


def cmd_channel(a):
    print(json.dumps(channels(youtube()), indent=2))


def cmd_meta(a):
    meta = build_meta(a)
    out = Path(a.out) if a.out else Path(meta["context"]["work"]) / "export" / f"youtube_rank{a.rank}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n")
    print(f"META {out}\n\nTITLE\n{meta['title']}\n\nDESCRIPTION\n{meta['description']}\n\n"
          f"TAGS {', '.join(meta['tags'])}\nFILE {meta['file']}")
    for w in meta["warnings"]:
        print(f"WARNING {w}")


def cmd_upload(a):
    meta_path = Path(a.meta)
    m = json.loads(meta_path.read_text())
    file = a.file or m.get("file")
    if not file or not Path(file).exists():
        sys.exit(f"clip not found: {file}")
    if m.get("youtube") and not a.again:
        sys.exit(f"already uploaded as {m['youtube']['url']} (pass --again to upload a second copy)")
    from googleapiclient.http import MediaFileUpload

    yt = youtube()
    chans = channels(yt)
    want = a.expect_channel.lower().lstrip("@")
    if not any(want in (c["id"].lower(), c["title"].lower(), c["handle"].lower().lstrip("@")) for c in chans):
        sys.exit(f"token uploads to {chans}, not {a.expect_channel!r}: nothing uploaded")

    body = {"snippet": {"title": m["title"], "description": m["description"], "tags": m.get("tags", []),
                        "categoryId": m.get("categoryId", "17")},
            "status": {"privacyStatus": a.privacy, "selfDeclaredMadeForKids": False}}
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(file, chunksize=8 * 1024 * 1024, resumable=True))
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"uploaded {status.progress():.0%}", flush=True)
    url = f"https://youtu.be/{resp['id']}"
    print("VIDEO", resp["id"], url, resp["status"]["privacyStatus"])
    record(meta_path, m, url, resp["status"]["privacyStatus"], chans[0])


def cmd_record(a):
    meta_path = Path(a.meta)
    record(meta_path, json.loads(meta_path.read_text()), a.url, a.privacy, None)


def record(meta_path, m, url, privacy, channel):
    """Save the URL in the meta JSON, result.json (`uploads`) and the track README results table."""
    entry = {"url": url, "privacy": privacy, "channel": channel,
             "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    m["youtube"] = entry
    meta_path.write_text(json.dumps(m, indent=1, ensure_ascii=False) + "\n")

    ctx = m["context"]
    res_path = Path(ctx["work"]) / "result.json"
    res = json.loads(res_path.read_text())
    res.setdefault("uploads", []).append({"rank": ctx["rank"], "video": ctx["video"],
                                          "total": ctx["total"], **entry})
    res_path.write_text(json.dumps(res, indent=1) + "\n")
    print(f"saved in {meta_path} and {res_path}")

    if ctx.get("readme"):
        print(update_readme(Path(ctx["readme"]), ctx["video"], f"{ctx['total']:.2f}", url))


def update_readme(path, video, total, url):
    """Fill the YouTube column of the results-table row for this video and total."""
    lines = path.read_text(encoding="utf-8").split("\n")
    for i, line in enumerate(lines):
        if not line.startswith("|") or "YouTube" not in line:
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        yt_col = cols.index("YouTube")
        for j in range(i + 2, len(lines)):
            if not lines[j].startswith("|"):
                break
            row = [c.strip() for c in lines[j].strip("|").split("|")]
            if video in lines[j] and total in lines[j] and len(row) == len(cols):
                if url in row[yt_col]:
                    return f"README already lists {url}"
                row[yt_col] = url if row[yt_col] in ("", "-") else f"{row[yt_col]}, {url}"
                lines[j] = "| " + " | ".join(row) + " |"
                path.write_text("\n".join(lines), encoding="utf-8")
                return f"README updated: {path}"
    return f"README NOT updated: no results row with {video} and {total} s in {path}; add it by hand"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("auth", help="one-time Google sign-in")
    p.add_argument("--client", required=True, help="OAuth desktop client file (client_secret_*.json)")
    sub.add_parser("channel", help="show the channel the token uploads to")

    p = sub.add_parser("meta", help="build title, description and tags from a fpv-best-laps run")
    p.add_argument("--work", required=True, help="fpv-best-laps work folder (has result.json)")
    p.add_argument("--rank", type=int, default=1, help="which ranked result (default 1)")
    p.add_argument("--readme", help="track folder README (default: found next to the videos)")
    p.add_argument("--race", help="RaceGOW season number (default: from folder names)")
    p.add_argument("--track", help="track number (default: from folder names)")
    p.add_argument("--pilot", default="PAPFPV")
    p.add_argument("--quad", default="Air65", help="craft name, as in the OSD")
    p.add_argument("--video-system", help="default: from the file names (hdz_ = HDZero)")
    p.add_argument("--date", help="date flown, YYYY-MM-DD (default: from the video file)")
    p.add_argument("--sponsor", help="track sponsor (default: from the demo title in the README)")
    p.add_argument("--designer", help="track designer (default: from the demo title in the README)")
    p.add_argument("--about-line", help="sponsor/designer sentence (default: from the demo description)")
    p.add_argument("--deadline", help='default: from the demo video description, e.g. "Sunday, October 25th at 11:59pm PST"')
    p.add_argument("--offline", action="store_true", help="don't read the demo video description")
    p.add_argument("--leaderboard", help="racegow-leaderboard JSON (default: run that skill now)")
    p.add_argument("--no-rank", action="store_true", help="leave the leaderboard rank out")
    p.add_argument("--out", help="default: <work>/export/youtube_rank<N>.json")

    p = sub.add_parser("upload", help="upload the clip described by a meta JSON")
    p.add_argument("--meta", required=True)
    p.add_argument("--privacy", required=True, choices=["private", "unlisted", "public"],
                   help="the pilot's call on every upload")
    p.add_argument("--expect-channel", required=True,
                   help="channel id, title or @handle the pilot confirmed; refuses to upload elsewhere")
    p.add_argument("--file", help="clip to upload (default: the meta JSON's file)")
    p.add_argument("--again", action="store_true", help="upload even if this meta was uploaded before")

    p = sub.add_parser("record", help="save the URL of a video uploaded some other way")
    p.add_argument("--meta", required=True)
    p.add_argument("--url", required=True)
    p.add_argument("--privacy", default="public", choices=["private", "unlisted", "public"])

    a = ap.parse_args()
    {"auth": cmd_auth, "channel": cmd_channel, "meta": cmd_meta, "upload": cmd_upload,
     "record": cmd_record}[a.cmd](a)


if __name__ == "__main__":
    main()
