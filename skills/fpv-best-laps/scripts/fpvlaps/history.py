"""Progress across sessions and consistency stats, read from the saved result.json files (no database).

    python fpvlaps.py history --track Track2              (a track name, matched in the session paths)
    python fpvlaps.py history --track /mnt/c/.../Track2   (or the track folder itself)

A session is one analysed batch folder = one work directory under --work-root (default ./fpvlaps-work),
read from <work-root>/*/result.json (folders nested inside a work directory, e.g. old experiments,
are not sessions). A session belongs to the track when its batch folder, track README or track
profile lies inside the track folder, or when a folder in its path is named after the track
(`Track2`, `Track2-1st`, but not `Track20`). The same footage analysed twice counts once (newest run).

Writes history.html (charts + table), history.json, and a link in every session's report.md. The
default output folder is the track folder (next to README.md / track.json), else the work root."""
import html
import json
import os
import re
import statistics
from datetime import datetime
from pathlib import Path

LINK_START, LINK_END = "<!-- history -->", "<!-- /history -->"
MIN_YEAR = 2015                          # goggles without a real-time clock write default dates


# ---------------------------------------------------------------- per-session stats

def is_crash(lap):
    """A rejected lap the quad didn't fly to the end: disarmed or stopped inside the lap."""
    return not lap["clean"] and ("disarmed" in lap["reason"] or "quad stopped" in lap["reason"])


def session_stats(R):
    """Consistency of one session: clean-lap spread, best vs median, bad-lap and crash rate."""
    laps = R["laps"]
    C = sorted(l["time"] for l in laps if l["clean"])
    n = len(laps)
    s = dict(laps=n, clean=len(C), clean_pct=len(C) / n * 100 if n else 0.0,
             bad_pct=(n - len(C)) / n * 100 if n else 0.0,
             crashes=sum(is_crash(l) for l in laps),
             best_lap=C[0] if C else None, median_lap=statistics.median(C) if C else None,
             std_lap=statistics.stdev(C) if len(C) > 1 else None,
             best3=R["best"][0]["total"] if R.get("best") else None,
             best3_video=R["best"][0]["video"] if R.get("best") else None)
    s["crash_pct"] = s["crashes"] / n * 100 if n else 0.0
    s["gap_lap"] = s["median_lap"] - s["best_lap"] if C else None
    return s


def consistency_lines(R):
    """The report.md consistency section."""
    s = session_stats(R)
    if not s["clean"]:
        return ["## Consistency", "", "No clean laps in this session.", ""]
    f = lambda v: "-" if v is None else f"{v:.2f}s"          # noqa: E731
    return ["## Consistency", "",
            "| Clean laps | Std dev | Best lap | Median lap | Best to median | Bad laps | Crashes |",
            "|---|---|---|---|---|---|---|",
            f"| {s['clean']} of {s['laps']} ({s['clean_pct']:.0f}%) | {f(s['std_lap'])} | {f(s['best_lap'])} | "
            f"{f(s['median_lap'])} | +{s['gap_lap']:.2f}s | {s['bad_pct']:.0f}% | {s['crashes']} ({s['crash_pct']:.0f}%) |",
            "", "Std dev and median are over clean laps only. Bad laps = every rejected lap (off-line, missed gate, "
            "disarm, stall, too fast); crashes = laps disarmed or stopped before the finish.", ""]


def link_block(path, n_sessions=None):
    """The report.md line pointing at history.html (or saying how to make it), between markers so
    `history` can refresh it in place."""
    if path is None:
        return [LINK_START, "Progress across sessions: run `fpvlaps.py history --track <track folder>`.", LINK_END]
    what = f" ({n_sessions} sessions)" if n_sessions else ""
    return [LINK_START, f"Progress across sessions{what}: `{path}`", LINK_END]


def history_link_for(R):
    """history.html next to this session's track README, if one was written."""
    readme = (R.get("track_readme") or {}).get("path")
    p = Path(readme).parent / "history.html" if readme else None
    return p if p and p.is_file() else None


def set_report_link(report, path, n_sessions):
    """Insert or refresh the history link in a report.md (idempotent)."""
    text = report.read_text()
    block = "\n".join(link_block(path, n_sessions))
    if LINK_START in text and LINK_END in text:
        text = re.sub(re.escape(LINK_START) + r".*?" + re.escape(LINK_END), lambda m: block, text, flags=re.S)
    else:
        text = text.rstrip("\n") + "\n\n" + block + "\n"
    report.write_text(text)


# ---------------------------------------------------------------- finding the sessions

def _date_in(name):
    m = re.search(r"(20\d\d)-(\d\d)-(\d\d)", name)
    if m:
        try:
            return datetime(*map(int, m.groups())).date()
        except ValueError:
            pass
    return None


def session_date(R, work):
    """(date, source): a YYYY-MM-DD batch folder name, the recordings' file dates, or the first analysis."""
    vd = R.get("videos_dir") or ""
    d = _date_in(Path(vd).name)
    if d:
        return d, "folder name"
    times = []
    for v in R["videos"]:
        p = Path(v["path"])
        if not p.is_absolute() and vd:
            p = Path(vd) / p.name
        try:
            t = datetime.fromtimestamp(p.stat().st_mtime)
        except OSError:
            continue
        if t.year >= MIN_YEAR:
            times.append(t)
    if times:
        return sorted(times)[len(times) // 2].date(), "file dates"
    feats = list((Path(work) / "features").glob("*.json")) or [Path(work) / "result.json"]
    return datetime.fromtimestamp(min(p.stat().st_mtime for p in feats)).date(), "analysis date"


def _inside(p, folder):
    try:
        return Path(os.path.realpath(p)).is_relative_to(folder)
    except (OSError, ValueError):
        return False


def _named(p, name):
    pat = re.compile(re.escape(name) + r"(?![0-9a-z])", re.I)
    return any(pat.match(part) for part in Path(p).parts)


def belongs(R, work, folder, name):
    paths = [R.get("videos_dir"), (R.get("track_readme") or {}).get("path"), R.get("track_profile")]
    paths = [p for p in paths if p]
    if folder and any(_inside(p, folder) for p in paths):
        return True
    return any(_named(p, name) for p in paths + [Path(work).name])


def collect(track, work_root, log=print):
    """Sessions of the track, oldest first: [dict(work, batch, date, date_source, **session_stats)]."""
    folder = Path(os.path.realpath(track)) if Path(track).is_dir() else None
    name = Path(track).name
    found = {}
    for rp in sorted(Path(work_root).glob("*/result.json")):
        try:
            R = json.loads(rp.read_text())
        except (OSError, ValueError) as e:
            log(f"  skipping {rp}: {e}")
            continue
        if not R.get("laps") or not belongs(R, rp.parent, folder, name):
            continue
        key = tuple(sorted((v["name"], round(v.get("seconds", 0), 1)) for v in R["videos"]))
        if key in found and found[key][0].stat().st_mtime >= rp.stat().st_mtime:
            log(f"  {rp.parent.name}: same footage as {found[key][0].parent.name}, keeping the newer run")
            continue
        if key in found:
            log(f"  {found[key][0].parent.name}: same footage as {rp.parent.name}, keeping the newer run")
        found[key] = (rp, R)
    out = []
    for rp, R in found.values():
        d, src = session_date(R, rp.parent)
        out.append(dict(work=str(rp.parent), batch=Path(R.get("videos_dir") or rp.parent).name,
                        date=d.isoformat(), date_source=src, readme=(R.get("track_readme") or {}).get("path"),
                        **session_stats(R)))
    out.sort(key=lambda s: (s["date"], s["batch"]))
    return out, folder


# ---------------------------------------------------------------- the page

def _ticks(lo, hi, n=4):
    """Clean tick values covering [lo, hi]."""
    if hi <= lo:
        lo, hi = lo - 1, hi + 1
    raw = (hi - lo) / n
    mag = 10 ** int(f"{raw:e}".split("e")[1])
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    t0 = int(lo // step) * step
    out = []
    while t0 <= hi + step * 0.999:
        out.append(round(t0, 6))
        t0 += step
    return out


def _chart(sessions, series, unit, title, subtitle):
    """One small-multiple line chart (inline SVG). series = [(key, label, css var)]."""
    W, H, L, Rm, T, B = 560, 220, 44, 64, 12, 44
    pts = [s[k] for s in sessions for k, _, _ in series if s[k] is not None]
    if not pts:
        return f'<section class="chart"><h2>{title}</h2><p class="sub">No data yet.</p></section>'
    ticks = _ticks(min(pts), max(pts)) if unit != "%" else [0, 25, 50, 75, 100]
    y0, y1 = ticks[0], ticks[-1]
    n = len(sessions)
    xs = [L + (W - L - Rm) * (i / (n - 1) if n > 1 else 0.5) for i in range(n)]
    Y = lambda v: T + (H - T - B) * (1 - (v - y0) / (y1 - y0))          # noqa: E731
    fmt = (lambda v: f"{v:.0f}%") if unit == "%" else (lambda v: f"{v:.2f} s")    # noqa: E731
    g = [f'<line class="grid" x1="{L}" x2="{W - Rm}" y1="{Y(t):.1f}" y2="{Y(t):.1f}"/>'
         f'<text class="tick" x="{L - 6}" y="{Y(t) + 4:.1f}" text-anchor="end">{t:g}</text>' for t in ticks]
    for i, s in enumerate(sessions):
        g.append(f'<text class="tick" x="{xs[i]:.1f}" y="{H - B + 20}" text-anchor="middle">{s["date"][5:]}</text>'
                 f'<text class="tick muted" x="{xs[i]:.1f}" y="{H - B + 34}" text-anchor="middle">'
                 f'{html.escape(s["batch"][:12])}</text>')
    ends = []
    for k, label, var in series:
        P = [(xs[i], Y(s[k]), s) for i, s in enumerate(sessions) if s[k] is not None]
        if len(P) > 1:
            g.append(f'<polyline class="line" style="stroke:var({var})" points="'
                     + " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in P) + '"/>')
        for x, y, s in P:
            tip = html.escape(f"{label}: {fmt(s[k])}\n{s['date']} · {s['batch']}")
            g.append(f'<g class="pt"><circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="4.5" style="fill:var({var})"/>'
                     f'<circle class="hit" cx="{x:.1f}" cy="{y:.1f}" r="12"><title>{tip}</title></circle></g>')
        x, y, s = P[-1]
        ends.append([y, fmt(s[k]), x])                  # the legend names the series
    ends.sort()
    for a, b in zip(ends, ends[1:]):                    # keep end labels from overlapping
        if b[0] - a[0] < 14:
            b[0] = a[0] + 14
    for y, text, x in ends:
        g.append(f'<text class="end" x="{x + 10:.1f}" y="{y + 4:.1f}">{html.escape(text)}</text>')
    legend = ""
    if len(series) > 1:
        legend = '<div class="legend">' + "".join(
            f'<span><i style="background:var({v})"></i>{html.escape(lb)}</span>' for _, lb, v in series) + "</div>"
    return (f'<section class="chart"><h2>{title}</h2><p class="sub">{subtitle}</p>{legend}'
            f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(title)}">{"".join(g)}</svg></section>')


def _table(sessions):
    f = lambda v, u="s": "–" if v is None else (f"{v:.0f}%" if u == "%" else f"{v:.2f}")   # noqa: E731
    head = ("Date", "Batch", "Laps", "Clean", "Best lap", "Median", "Std dev", "Best→median", "Best 3", "Crashes")
    rows = ["<tr>" + "".join(f"<th>{h}</th>" for h in head) + "</tr>"]
    for s in sessions:
        rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in (
            f'{s["date"]}<span class="muted"> ({s["date_source"]})</span>', html.escape(s["batch"]), s["laps"],
            f'{s["clean"]} ({f(s["clean_pct"], "%")})', f(s["best_lap"]), f(s["median_lap"]), f(s["std_lap"]),
            f(s["gap_lap"]), f(s["best3"]), f'{s["crashes"]} ({f(s["crash_pct"], "%")})')) + "</tr>")
    return '<div class="table"><table>' + "".join(rows) + "</table></div>"


CSS = """
:root{color-scheme:light;--surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--ring:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--surface:#1a1a19;
--page:#0d0d0d;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--ring:rgba(255,255,255,.10);
--s1:#3987e5;--s2:#d95926}}
:root[data-theme="dark"]{color-scheme:dark;--surface:#1a1a19;--page:#0d0d0d;--ink:#f0efec;--ink2:#c3c2b7;
--muted:#898781;--grid:#2c2c2a;--ring:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:760px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:15px;margin:0}
.sub,.muted{color:var(--ink2)}.muted{color:var(--muted)}
.chart,.table{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:16px;margin:16px 0}
.sub{margin:2px 0 8px;font-size:13px}
svg{width:100%;height:auto;display:block;overflow:visible}
.grid{stroke:var(--grid);stroke-width:1}
.tick{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}
.end{fill:var(--ink2);font-size:12px;font-weight:600}
.line{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.dot{stroke:var(--surface);stroke-width:2}
.hit{fill:transparent;cursor:default}.pt:hover .dot{r:6}
.legend{display:flex;gap:16px;font-size:13px;color:var(--ink2);margin-bottom:6px}
.legend i{display:inline-block;width:14px;height:3px;border-radius:2px;margin-right:6px;vertical-align:middle}
.table{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--grid);white-space:nowrap}
th:nth-child(-n+2),td:nth-child(-n+2){text-align:left}
th{color:var(--ink2);font-weight:600}
"""


def page(name, sessions):
    first, last = sessions[0], sessions[-1]
    lede = f"{len(sessions)} session{'s' if len(sessions) != 1 else ''}, {first['date']} to {last['date']}."
    charts = [
        _chart(sessions, [("best_lap", "Best lap", "--s1"), ("median_lap", "Median clean lap", "--s2")], "s",
               "Lap time", "Seconds, lower is better. The gap between the lines is how far a typical lap is "
                           "from the best one."),
        _chart(sessions, [("best3", "Best 3 consecutive", "--s1")], "s", "Best 3 consecutive laps",
               "Total seconds, lower is better."),
        _chart(sessions, [("clean_pct", "Clean laps", "--s1")], "%", "Clean laps",
               "Share of all detected laps that were clean, higher is better."),
    ]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(name)} progress</title><style>{CSS}</style></head>
<body><main>
<h1>{html.escape(name)}: progress across sessions</h1>
<p class="sub">{lede} One point per analysed batch, evenly spaced; hover a point for its value.
Generated by fpv-best-laps <code>history</code> on {datetime.now():%Y-%m-%d}.</p>
{"".join(charts)}
<h2>Every session</h2>
{_table(sessions)}
<p class="sub">Median and std dev are over clean laps. Crashes = laps disarmed or stopped before the finish.
Dates come from a YYYY-MM-DD batch folder name, else the recordings' file dates, else the first analysis.</p>
</main></body></html>
"""


def write_history(track, work_root="fpvlaps-work", out=None, log=print):
    sessions, folder = collect(track, work_root, log)
    name = Path(track).name
    if not sessions:
        raise SystemExit(f"No result.json under {work_root}/*/ belongs to track {track!r}: analyse a batch "
                         "first, or pass --work-root / the track folder as --track")
    if out is None:
        readmes = {Path(s["readme"]).parent for s in sessions if s["readme"]}
        out = folder or (readmes.pop() if len(readmes) == 1 else Path(work_root))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    html_p = out / ("history.html" if out != Path(work_root) else f"history-{name}.html")
    html_p.write_text(page(name, sessions))
    (html_p.with_suffix(".json")).write_text(json.dumps(dict(track=name, sessions=sessions), indent=1))
    for s in sessions:
        log(f"  {s['date']} {s['batch']:<14} best lap {s['best_lap'] or 0:6.2f}  best 3 {s['best3'] or 0:6.2f}  "
            f"median {s['median_lap'] or 0:6.2f}  clean {s['clean_pct']:3.0f}%  ({Path(s['work']).name})")
        rep = Path(s["work"]) / "report.md"
        if rep.is_file():
            set_report_link(rep, html_p.resolve(), len(sessions))
    log(f"  history: {html_p} (+ {html_p.with_suffix('.json').name}); linked from {len(sessions)} report.md")
    return html_p
