"""Track folder README: the track's reference, picked up automatically.

Recordings are kept per track, one subfolder per batch:

    Track2/
      README.md          demo video, flythrough start, one lap known to be correct
      track.json + .npz  verified track profile (optional, saved with `save-track`)
      1st/  2nd/ ...     batches of DVR files

The README lines the tool reads (anywhere in the file, bold labels as shown):

    **Demo video:** https://www.youtube.com/watch?v=... ("title")
    **Flythrough starts at:** 1:00
    **Correct lap:** 1st/hdz_0022 at 0:58.98      (or: 1st/hdz_0022 frame 3539)

The correct-lap video path is relative to the README's folder; the time or frame is a start-gate
crossing that begins a lap the pilot has checked against the demo."""
import os
import re
from pathlib import Path
from .config import VIDEO_EXTS

README = "README.md"


def find_readme(videos_dir):
    """README.md in the batch folder itself, else in its parent (the track folder). The parent is taken
    from the path as given, not after following symlinks: a linked batch folder belongs to the track
    folder it's linked into."""
    d = Path(os.path.abspath(videos_dir))
    for c in (d / README, d.parent / README):
        if c.is_file():
            return c
    return None


def parse_clock(s):
    """'59', '0:58.98', '1:02:03' -> seconds."""
    sec = 0.0
    for part in s.split(":"):
        sec = sec * 60 + float(part)
    return sec


def parse_readme(path):
    """{demo, demo_title, flythrough, correct_lap: {video, time|frame}} from the README (missing keys
    are left out)."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    info = {}
    m = re.search(r"\*\*Demo video:\*\*\s*(\S+)(?:\s*\(\"([^\"]+)\")?", text)
    if m:
        info["demo"] = m.group(1)
        if m.group(2):
            info["demo_title"] = " ".join(m.group(2).split())       # the title may wrap lines
    m = re.search(r"\*\*Flythrough starts at:\*\*\s*(\d+:\d{2}(?::\d{2})?)", text)
    if m:
        info["flythrough"] = m.group(1)
    m = re.search(r"\*\*Correct lap:\*\*\s*`?([^`\s]+)`?\s+(?:at\s+(\d+(?::\d{1,2})*(?:\.\d+)?)|frame\s+(\d+))",
                  text, re.I)
    if m:
        lap = dict(video=m.group(1))
        if m.group(3):
            lap["frame"] = int(m.group(3))
        else:
            lap["time"] = parse_clock(m.group(2))
        info["correct_lap"] = lap
    return info


def demo_link(info):
    """Demo URL that opens at the flythrough (YouTube `t=` parameter), or the plain URL."""
    url = info.get("demo")
    if not url or not info.get("flythrough"):
        return url
    if "youtu" not in url or "t=" in url:
        return url
    return f"{url}{'&' if '?' in url else '?'}t={int(parse_clock(info['flythrough']))}s"


def resolve_video(readme, rel):
    """Correct-lap video path (relative to the README folder; the extension may be left out)."""
    p = (Path(readme).parent / rel).resolve()
    if p.suffix.lower() in VIDEO_EXTS and p.is_file():
        return p
    for ext in VIDEO_EXTS:
        for q in (p.with_name(p.name + ext), p.with_name(p.name + ext.upper())):
            if q.is_file():
                return q
    raise SystemExit(f"Correct lap in {readme}: video {rel} not found next to the README")


def choose_reference(videos_dir, track=None, anchor=None, readme=None, use_readme=True):
    """Which reference to time laps against, in order: --track / --anchor from the command line, the
    track.json next to the README, the README's correct lap, automatic calibration.

    Returns dict(readme, info, track, anchor, correct_lap, how) where `how` says what was chosen."""
    out = dict(readme=None, info={}, track=track, anchor=anchor, correct_lap=None)
    if use_readme:
        rd = Path(readme) if readme else find_readme(videos_dir)
        if readme and not rd.is_file():
            raise SystemExit(f"--readme {readme} not found")
        if rd:
            out["readme"] = rd.resolve()
            out["info"] = parse_readme(rd)
    if track:
        out["how"] = f"track profile {track} (--track)"
    elif anchor:
        out["how"] = f"start-gate crossing {anchor} (--anchor)"
    elif out["readme"] and (out["readme"].parent / "track.json").is_file():
        out["track"] = str(out["readme"].parent / "track.json")
        out["how"] = f"track profile {out['track']} (next to the track README)"
    elif out["info"].get("correct_lap"):
        lap = dict(out["info"]["correct_lap"])
        lap["path"] = resolve_video(out["readme"], lap["video"])
        out["correct_lap"] = lap
        at = f"frame {lap['frame']}" if "frame" in lap else f"at {lap['time']:.2f}s"
        out["how"] = f"correct lap {lap['video']} {at} (track README)"
    else:
        out["how"] = "automatic calibration" + (" (the track README has no track.json or correct lap)"
                                                if out["readme"] else "")
    return out


def save_track(work, dest=None, force=False, log=print):
    """Copy a verified run's track.json + track.npz from <work> next to the track README (or to `dest`),
    so later batches of the same track reuse it. Refuses to overwrite an existing profile unless
    `force`, and then keeps the old one as track.json.bak / track.npz.bak."""
    import json
    import shutil
    work = Path(work)
    rp = work / "result.json"
    if not rp.is_file():
        raise SystemExit(f"No result.json in {work}: run `analyze` first")
    R = json.loads(rp.read_text())
    if R.get("track_profile"):
        raise SystemExit(f"This run reused the track profile {R['track_profile']}; there is no new profile to save")
    src = [work / "track.json", work / "track.npz"]
    if not all(p.is_file() for p in src):
        raise SystemExit(f"No track.json + track.npz in {work}")
    if dest is None:
        readme = (R.get("track_readme") or {}).get("path")
        if not readme:
            raise SystemExit("No track README was found for this run: pass --to <track folder>")
        dest = Path(readme).parent
    dest = Path(dest)
    dst = [dest / p.name for p in src]
    if any(p.exists() for p in dst):
        if not force:
            raise SystemExit(f"{dest / 'track.json'} already exists. It may be the verified profile other "
                             "batches rely on; pass --force to replace it (the old one is kept as .bak)")
        for p in dst:
            if p.exists():
                shutil.copy2(p, p.with_name(p.name + ".bak"))
                log(f"  kept the old {p.name} as {p.name}.bak")
    for s, d in zip(src, dst):
        shutil.copy2(s, d)
    ref = R["reference"]
    log(f"  saved {dst[0]} + {dst[1].name} (reference {ref['video']} {ref['start']}->{ref['end']})")
    return dst[0]
