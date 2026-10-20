"""Side-by-side lap comparison: two laps of a track (same or different sessions), each starting on its own
gate frame, with both lap clocks and the running gap at every point of the lap.

    python fpvlaps.py compare --work fpvlaps-work/Track2-2nd                  (default pair, see below)
    python fpvlaps.py compare --lap Track2-2nd/hdz_0023:best --lap Track2-1st/hdz_0022@106.8

A lap is `[SESSION/]VIDEO:N` (the Nth lap of that video, in laps.csv order), `[SESSION/]VIDEO@SECONDS`
(the lap starting nearest that time, as report.md writes them) or `[SESSION/]VIDEO:best` (its fastest
clean lap). SESSION is a work directory, or its name under --work-root; without it the lap comes from
--work, else from the one session under --work-root that has a video of that name.

Default pair (no --lap): the best clean lap of the --work session against the best clean lap ever on
the track (every session `history` would collect); when this session holds the track's best lap, the
next fastest lap on the track.

Running gap: the two laps' 20 Hz descriptors are aligned by fixed-endpoint DTW (sectors.align), which
maps every point of lap A to the same point of the course in lap B. gap(t) = how much longer lap A took
to reach the point it reaches t seconds into its lap, smoothed over 0.5 s and pinned to 0 at the start
gate and to the lap-time difference at the finish. Sector deltas read the gap at lap A's sector
boundaries (its saved sector splits, else lap B's mapped across, else an even split of lap A).

Writes <work of lap A>/compare/<A>_vs_<B>/: compare.md, compare.json, gap.png and the video
(1920x1080, A left / B right, gap chart below; OpenCV by default, HyperFrames with --renderer
hyperframes, which is much slower for this composition; audio of one lap or none)."""
import json
import re
import shutil
import subprocess
from pathlib import Path
import numpy as np
import cv2
from .config import ASSETS, DTW_STEP, REFINE_WINDOW, SECTORS_DEFAULT
from .laps import dtw_desc, fine_desc, refine, window
from .media import ffmpeg_exe, env_with_tools
from .render import HYPERFRAMES, hyperframes_ready
from .sectors import align

SMOOTH_S = 0.5                     # running gap smoothed over this window
SNAP_SEARCH = 15                   # +- frames a mapped sector boundary may move when snapped at 60 fps
MOMENT_S = 1.5                     # window for "where lap A loses / gains most"
W, H = 1920, 1080                  # output canvas
# colours: A = categorical slot 1 (blue), B = slot 2 (orange), dark-surface steps (the canvas is dark)
COL_A, COL_B = "#3987e5", "#d95926"
BG, INK, INK2, MUTED, GRID = "#0d0d0d", "#f0efec", "#c3c2b7", "#898781", "#2c2c2a"


# ---------------------------------------------------------------- choosing the laps

def load_result(work):
    p = Path(work) / "result.json"
    if not p.is_file():
        raise SystemExit(f"No result.json in {work}: run `fpvlaps.py analyze` first")
    return json.loads(p.read_text())


def session_dir(name, work, work_root):
    """A session given as a path or a work directory name under work_root."""
    for p in (Path(name), Path(work_root) / name):
        if (p / "result.json").is_file():
            return p
    raise SystemExit(f"Session {name!r}: no result.json there or under {work_root}")


def video_laps(R, video):
    return sorted((l for l in R["laps"] if l["video"] == video), key=lambda l: l["start"])


def pick_lap(R, video, which, where):
    laps = video_laps(R, video)
    if not laps:
        names = sorted({l["video"] for l in R["laps"]})
        raise SystemExit(f"{where}: no laps of {video!r} (videos with laps: {', '.join(names)})")
    if which in ("", "best"):
        clean = [l for l in laps if l["clean"]]
        if not clean:
            raise SystemExit(f"{where}: {video} has no clean lap; give one by number or time")
        return min(clean, key=lambda l: l["time"])
    if which.startswith("@"):
        t = float(which[1:].rstrip("s")) * R["fps"]
        return min(laps, key=lambda l: abs(l["start"] - t))
    try:
        n = int(which)
    except ValueError:
        raise SystemExit(f"{where}: lap {which!r}: use a number, @SECONDS or best")
    if not 1 <= n <= len(laps):
        raise SystemExit(f"{where}: {video} has {len(laps)} laps (1-{len(laps)})")
    return laps[n - 1]


def parse_lap(spec, work=None, work_root="fpvlaps-work"):
    """'[SESSION/]VIDEO:N|:best|@SECONDS' -> dict(work, R, lap, number, label)."""
    session, _, rest = spec.rpartition("/")
    m = re.fullmatch(r"(.+?)(?::(best|\d+)|(@[\d.]+s?))?", rest)
    if not m:
        raise SystemExit(f"--lap {spec!r}: expected [SESSION/]VIDEO:N, VIDEO@SECONDS or VIDEO:best")
    video = Path(m.group(1)).stem
    which = m.group(2) or m.group(3) or "best"
    if session:
        wd = session_dir(session, work, work_root)
    elif work:
        wd = Path(work)
    else:
        hits = [p.parent for p in sorted(Path(work_root).glob("*/result.json"))
                if any(l["video"] == video for l in json.loads(p.read_text()).get("laps", []))]
        if len(hits) != 1:
            raise SystemExit(f"--lap {spec!r}: {'no' if not hits else len(hits)} sessions under {work_root} have "
                             f"laps of {video}" + (f" ({', '.join(h.name for h in hits)}); prefix SESSION/" if hits else ""))
        wd = hits[0]
    R = load_result(wd)
    lap = pick_lap(R, video, which, f"--lap {spec}")
    return describe(wd, R, lap)


def describe(work, R, lap, role=""):
    n = [l["start"] for l in video_laps(R, lap["video"])].index(lap["start"]) + 1
    batch = Path(R.get("videos_dir") or work).name
    return dict(work=str(work), R=R, lap=lap, number=n, role=role, session=Path(work).name, batch=batch,
                label=f"{Path(work).name} · {lap['video']} @ {lap['start'] / R['fps']:.1f}s",
                short=f"{lap['video']} lap {n}")


def track_of(R, work):
    """The track folder (README's folder, else the batch folder's parent) or None."""
    readme = (R.get("track_readme") or {}).get("path")
    if readme and Path(readme).parent.is_dir():
        return str(Path(readme).parent)
    vd = R.get("videos_dir")
    if vd and Path(vd).parent.is_dir():
        return str(Path(vd).parent)
    return None


def default_pair(work, work_root="fpvlaps-work", log=print):
    from .history import collect
    R = load_result(work)
    clean = [l for l in R["laps"] if l["clean"]]
    if not clean:
        raise SystemExit(f"{work}: no clean laps to compare; give two laps with --lap")
    a = min(clean, key=lambda l: l["time"])
    track = track_of(R, work)
    sessions = collect(track, work_root, lambda *x: None)[0] if track else []
    works = {str(Path(s["work"]).resolve()): s["work"] for s in sessions}
    works.setdefault(str(Path(work).resolve()), str(work))
    cands = []
    for w in works.values():
        Rw = R if Path(w).resolve() == Path(work).resolve() else load_result(w)
        cands += [(l["time"], w, Rw, l) for l in Rw["laps"] if l["clean"]
                  and not (l["video"] == a["video"] and l["start"] == a["start"] and l["time"] == a["time"])]
    if not cands:
        raise SystemExit(f"{work}: only one clean lap on this track so far; give two laps with --lap")
    t, wb, Rb, b = min(cands, key=lambda c: c[0])
    role_b = "best lap on the track" if t <= a["time"] else "next fastest lap on the track"
    log(f"  default pair: best lap of this session vs the {role_b} ({len(works)} session(s) of "
        f"{Path(track).name if track else 'this track'})")
    return describe(work, R, a, "best lap this session"), describe(wb, Rb, b, role_b)


# ---------------------------------------------------------------- running gap

def features(work, video):
    d = Path(work) / "features"
    try:
        meta = json.loads((d / f"{video}.json").read_text())
        thumbs = np.load(d / f"{video}.thumbs.npy", mmap_mode="r")
    except OSError:
        raise SystemExit(f"Features of {video} missing in {d}: run `fpvlaps.py extract` for that session again")
    return meta, thumbs


def lap_desc(thumbs, lap):
    """20 Hz descriptors of one lap, step k = frame start + k*DTW_STEP."""
    return dtw_desc(thumbs[lap["start"]:lap["end"] + 1])


def gap_curve(XA, XB, nA, nB, fps):
    """gap[f] for f = 0..nA frames into lap A: seconds lap A is behind lap B at that point of the course
    (negative = ahead), and posB[f] = the frame of lap B at the same point."""
    path = align(XB, XA)
    pa = np.arange(len(XA), dtype=float) * DTW_STEP
    pb = np.array(path) * DTW_STEP if path is not None else pa * nB / nA       # proportional fallback
    pa, pb = np.r_[pa, nA], np.maximum.accumulate(np.r_[pb, nB])
    d = pa - pb                                                               # frames A is behind, per step
    k = max(1, int(round(SMOOTH_S * fps / DTW_STEP))) | 1
    d = np.convolve(np.pad(d, k // 2, mode="edge"), np.ones(k) / k, "valid")
    d -= d[0] + (d[-1] - d[0] - (nA - nB)) * pa / nA                          # pin both ends
    f = np.arange(nA + 1)
    gap = np.interp(f, pa, d) / fps
    posB = np.maximum.accumulate(f - gap * fps)
    return gap, posB


def fine_lap(thumbs, lap):
    """60 fps descriptors of a lap with +-0.5 s margin (for window()), and the frame of its index 0."""
    a = max(0, lap["start"] + min(REFINE_WINDOW) - SNAP_SEARCH)
    b = min(len(thumbs), lap["end"] + max(REFINE_WINDOW) + SNAP_SEARCH + 1)
    return fine_desc(thumbs[a:b]), a


def snap(gap, posB, edges, FA, FB, la, lb, fps, known=None):
    """Lap B's point at each sector boundary of lap A: `known` frames into lap B (both laps' own sector
    splits), else snapped to the exact frame (best match of the +-0.5 s view around it at 60 fps). The
    gap curve is bent through those points (piecewise linear)."""
    (FA, oa), (FB, ob) = FA, FB
    nA = len(gap) - 1
    fix = [0.0]
    for k, e in enumerate(edges):
        pb = float(posB[e])
        if known:
            c = known[k]
        else:
            w = window(FA, la["start"] + e - oa)
            if w is None:
                fix.append(0.0)
                continue
            c = refine(FB, lb["start"] + int(round(pb)) - ob, [w], SNAP_SEARCH)[0] + ob - lb["start"]
        fix.append((pb - c) / fps)                                         # gap = (fA - fB) / fps
    fix.append(0.0)
    gap = gap + np.interp(np.arange(nA + 1), [0] + list(edges) + [nA], fix)
    return gap, np.maximum.accumulate(np.arange(nA + 1) - gap * fps)


def same_sectors(A, B):
    """Both laps carry sector splits of the same reference-lap boundaries (same session or track profile)."""
    sa, sb = A["R"].get("sectors"), B["R"].get("sectors")
    ra, rb = A["R"]["reference"], B["R"]["reference"]
    return bool(A["lap"].get("sector_frames") and B["lap"].get("sector_frames") and sa and sb
                and sa["boundaries"] == sb["boundaries"]
                and (ra["video"], ra["start"], ra["end"]) == (rb["video"], rb["start"], rb["end"]))


def sector_edges(A, B, posB):
    """Interior sector boundaries as frames into lap A, and where they came from."""
    la, lb = A["lap"], B["lap"]
    nA = la["end"] - la["start"]
    if same_sectors(A, B):
        return [f - la["start"] for f in la["sector_frames"]], "both laps' sector splits (same reference lap)"
    if la.get("sector_frames"):
        return [f - la["start"] for f in la["sector_frames"]], f"lap A's sector splits ({A['session']})"
    if lb.get("sector_frames"):
        rel = [f - lb["start"] for f in lb["sector_frames"]]
        return ([int(round(np.interp(r, posB, np.arange(len(posB))))) for r in rel],
                f"lap B's sector splits ({B['session']}), mapped through the alignment")
    return ([int(round(nA * j / SECTORS_DEFAULT)) for j in range(1, SECTORS_DEFAULT)],
            "even split of lap A (no sector splits saved for these laps: re-run analyze)")


def moments(gap, fps, edges):
    """Where lap A loses and gains most over MOMENT_S, as (from_s, to_s, change_s, sector)."""
    w = int(MOMENT_S * fps)
    if len(gap) <= w:
        return []
    ch = gap[w:] - gap[:-w]
    out = []
    for kind, i in (("loss", int(np.argmax(ch))), ("gain", int(np.argmin(ch)))):
        if (kind == "loss" and ch[i] <= 0) or (kind == "gain" and ch[i] >= 0):
            continue
        mid = i + w // 2
        sec = 1 + sum(mid >= e for e in edges)
        out.append(dict(kind=kind, from_s=round(i / fps, 2), to_s=round((i + w) / fps, 2),
                        change_s=round(float(ch[i]), 3), sector=sec))
    return out


def compare_laps(A, B, log=print):
    fps = A["R"]["fps"]
    if abs(B["R"]["fps"] - fps) > 0.01:
        raise SystemExit(f"Laps recorded at different frame rates ({fps:g} / {B['R']['fps']:g} fps)")
    la, lb = A["lap"], B["lap"]
    nA, nB = la["end"] - la["start"], lb["end"] - lb["start"]
    _, ta = features(A["work"], la["video"])
    _, tb = features(B["work"], lb["video"])
    gap, posB = gap_curve(lap_desc(ta, la), lap_desc(tb, lb), nA, nB, fps)
    edges, src = sector_edges(A, B, posB)
    edges = [e for e in edges if 0 < e < nA]
    known = [f - lb["start"] for f in lb["sector_frames"]] if same_sectors(A, B) else None
    gap, posB = snap(gap, posB, edges, fine_lap(ta, la), fine_lap(tb, lb), la, lb, fps, known)
    ea, eb = [0] + edges + [nA], [0.0] + [float(posB[e]) for e in edges] + [nB]
    sa = [round((q - p) / fps, 3) for p, q in zip(ea, ea[1:])]
    sb = [round((q - p) / fps, 3) for p, q in zip(eb, eb[1:])]
    K = int(round(nA * 20 / fps)) + 1                                       # 20 Hz, last sample = the finish
    curve = np.interp(np.linspace(0, nA, K), np.arange(nA + 1), gap)
    lap_info = lambda X: dict(label=X["label"], short=X["short"], role=X["role"], session=X["session"],   # noqa: E731
                              work=X["work"], batch=X["batch"], video=X["lap"]["video"], number=X["number"],
                              start=X["lap"]["start"], end=X["lap"]["end"], time=X["lap"]["time"],
                              clean=X["lap"]["clean"], reason=X["lap"].get("reason", ""))
    C = dict(fps=fps, a=lap_info(A), b=lap_info(B), final_gap=round(la["time"] - lb["time"], 3),
             curve_hz=(K - 1) * fps / nA, curve=[round(float(g), 3) for g in curve],
             max_behind=dict(gap=round(float(gap.max()), 3), at_s=round(int(gap.argmax()) / fps, 2)),
             max_ahead=dict(gap=round(float(gap.min()), 3), at_s=round(int(gap.argmin()) / fps, 2)),
             sectors=dict(source=src, edges_a_s=[round(e / fps, 3) for e in edges], a=sa, b=sb,
                          delta=[round(x - y, 3) for x, y in zip(sa, sb)]),
             moments=moments(gap, fps, edges))
    for X in (A, B):
        if not X["lap"]["clean"]:
            log(f"  note: {X['label']} is not a clean lap ({X['lap'].get('reason', '')})")
    log(f"  A {A['label']} {la['time']:.2f}s vs B {B['label']} {lb['time']:.2f}s: "
        f"{fmt_gap(C['final_gap'])} at the finish; sectors " + ", ".join(
            f"S{k + 1} {fmt_gap(d)}" for k, d in enumerate(C["sectors"]["delta"])))
    return C, gap


def fmt_gap(g):
    return f"{'+' if g >= 0 else '-'}{abs(g):.2f}s"


def gap_words(g):
    return "level" if abs(g) < 0.005 else f"A {abs(g):.2f}s {'behind' if g > 0 else 'ahead'}"


# ---------------------------------------------------------------- outputs

def out_dir(A, B):
    la, lb = A["lap"], B["lap"]
    other = "" if A["work"] == B["work"] else B["session"] + "_"
    return Path(A["work"]) / "compare" / f"{la['video']}_{la['start']}_vs_{other}{lb['video']}_{lb['start']}"


def write_md(out, C, video=None):
    a, b, S = C["a"], C["b"], C["sectors"]
    row = lambda k, X: (f"| {k} | {X['label']} (lap {X['number']} of {X['video']}) | {X['time']:.2f}s | "   # noqa: E731
                        f"{X['role'] or '-'} | {'yes' if X['clean'] else 'no: ' + X['reason']} |")
    g = C["final_gap"]
    lines = ["# Lap comparison", "",
             "| | Lap | Time | Picked as | Clean |", "|---|---|---|---|---|", row("A", a), row("B", b), "",
             f"**A is {abs(g):.2f}s {'slower' if g > 0 else 'faster'} than B**." if abs(g) >= 0.005 else
             "**Both laps take the same time.**", "",
             "## Running gap", "",
             "Gap = how much longer lap A took to reach each point of the course than lap B (+ = A behind, "
             "- = A ahead). The two laps are aligned point by point (DTW of the picture descriptors), so the "
             "gap is known everywhere, not only at the finish. Chart: `gap.png`.", "",
             f"- A furthest behind: {fmt_gap(C['max_behind']['gap'])} at {C['max_behind']['at_s']:.1f}s into lap A",
             f"- A furthest ahead: {fmt_gap(C['max_ahead']['gap'])} at {C['max_ahead']['at_s']:.1f}s into lap A"]
    for m in C["moments"]:
        lines.append(f"- A {'loses' if m['kind'] == 'loss' else 'gains'} most from {m['from_s']:.1f}s to "
                     f"{m['to_s']:.1f}s (S{m['sector']}): {fmt_gap(m['change_s'])}")
    lines += ["", "## Sector deltas", "",
              f"Sectors: {S['source']}; boundaries at " + ", ".join(f"{e:.2f}s" for e in S["edges_a_s"])
              + " into lap A, the same points of the course in lap B.", "",
              "| Sector | A | B | A - B | Gap after |", "|---|---|---|---|---|"]
    cum = 0.0
    for k, (x, y, d) in enumerate(zip(S["a"], S["b"], S["delta"])):
        cum += d
        lines.append(f"| S{k + 1} | {x:.2f}s | {y:.2f}s | {'**' if d == max(S['delta']) and d > 0 else ''}"
                     f"{fmt_gap(d)}{'**' if d == max(S['delta']) and d > 0 else ''} | {fmt_gap(cum)} |")
    worst = int(np.argmax(S["delta"]))
    if S["delta"][worst] > 0:
        lines += ["", f"Most time lost in **S{worst + 1}** ({fmt_gap(S['delta'][worst])})."]
    lines += ["", f"Video: `{video.name}`" if video else
              "Video: run without `--no-video` to render the side-by-side clip.", ""]
    (out / "compare.md").write_text("\n".join(lines))


def bgr(hexs):
    h = hexs.lstrip("#")
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)


def ascii_(s):
    return s.replace("·", "-").replace("→", "->").encode("ascii", "replace").decode()


def _text(img, s, org, scale, color, weight=1):
    cv2.putText(img, ascii_(s), org, cv2.FONT_HERSHEY_DUPLEX, scale, bgr(color), weight, cv2.LINE_AA)


def _ticks(m):
    step = next(s for s in (0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5) if m / s <= 3)
    n = int(m / step + 1e-9)
    return [round(k * step, 3) for k in range(-n, n + 1)]


def chart_geometry(C, box):
    """Pixel mapping of the gap chart inside box = (x, y, w, h)."""
    x, y, w, h = box
    m = max(0.2, max(abs(v) for v in C["curve"])) * 1.15
    px0, px1, py0, py1 = x + 64, x + w - 16, y + 44, y + h - 26
    tA = C["a"]["time"]
    X = lambda t: int(round(px0 + (px1 - px0) * min(max(t, 0), tA) / tA))            # noqa: E731
    Y = lambda g: int(round((py0 + py1) / 2 - (py1 - py0) / 2 * g / m))             # noqa: E731
    return dict(X=X, Y=Y, m=m, px0=px0, px1=px1, py0=py0, py1=py1)


def draw_chart_static(img, C, box):
    """Gap chart parts that don't move: title, grid, sign-coloured area, the curve, sector dividers."""
    G = chart_geometry(C, box)
    X, Y = G["X"], G["Y"]
    _text(img, "GAP  A vs B", (box[0] + 16, box[1] + 24), 0.62, INK2, 1)
    _text(img, "+ = A behind  /  - = A ahead", (box[0] + 170, box[1] + 24), 0.5, MUTED, 1)
    for v in _ticks(G["m"]):
        yy = Y(v)
        cv2.line(img, (G["px0"], yy), (G["px1"], yy), bgr(GRID if v else "#383835"), 1, cv2.LINE_AA)
        _text(img, f"{v:+.2f}" if v else "0", (box[0] + 6, yy + 5), 0.45, MUTED)
    ts = np.arange(len(C["curve"])) / C["curve_hz"]
    pts = np.array([(X(tt), Y(g)) for tt, g in zip(ts, C["curve"])], np.int32)
    zero = Y(0)
    x, y, w, h = box
    sub = img[y:y + h, x:x + w]
    ov = sub.copy()
    for i in range(len(pts) - 1):                       # sign-coloured area: B colour above (A behind), A below
        a, b = pts[i] - (x, y), pts[i + 1] - (x, y)
        col = COL_B if (C["curve"][i] + C["curve"][i + 1]) > 0 else COL_A
        cv2.fillPoly(ov, [np.array([a, b, (b[0], zero - y), (a[0], zero - y)], np.int32)], bgr(col))
    cv2.addWeighted(ov, 0.35, sub, 0.65, 0, sub)
    cv2.polylines(img, [pts], False, bgr(INK2), 2, cv2.LINE_AA)
    _text(img, "A behind", (G["px1"] - 92, G["py0"] + 14), 0.45, MUTED)
    _text(img, "A ahead", (G["px1"] - 86, G["py1"] - 4), 0.45, MUTED)
    for e in C["sectors"]["edges_a_s"]:
        for yy in range(G["py0"], G["py1"], 10):
            cv2.line(img, (X(e), yy), (X(e), yy + 5), bgr(MUTED), 1)


def draw_chart_live(img, C, box, t=None):
    """Sector labels (each delta revealed once lap A passes the sector end), and at lap-A time t the
    cursor and gap readout; t=None = the finished chart without cursor."""
    G = chart_geometry(C, box)
    X, Y = G["X"], G["Y"]
    S = C["sectors"]
    tA = C["a"]["time"]
    done = tA if t is None else min(max(t, 0.0), tA)
    edges = [0.0] + S["edges_a_s"] + [tA]
    for k in range(len(edges) - 1):
        passed = done >= edges[k + 1] - 1e-6
        label = f"S{k + 1}" + (f" {fmt_gap(S['delta'][k])}" if passed else "")
        xm = (X(edges[k]) + X(edges[k + 1])) // 2
        _text(img, label, (xm - 6 * len(label), G["py1"] + 20), 0.5, INK if passed else MUTED)
    if t is not None:
        ts = np.arange(len(C["curve"])) / C["curve_hz"]
        xc = X(done)
        g = float(np.interp(done, ts, C["curve"]))
        cv2.line(img, (xc, G["py0"] - 6), (xc, G["py1"]), bgr(INK), 2, cv2.LINE_AA)
        cv2.circle(img, (xc, Y(g)), 6, bgr(INK), -1, cv2.LINE_AA)
        cv2.circle(img, (xc, Y(g)), 6, bgr(BG), 2, cv2.LINE_AA)
        _text(img, gap_words(g) if t > 0 else "start", (box[0] + box[2] - 330, box[1] + 26), 0.85, INK, 2)


def write_png(out, C):
    img = np.full((300, 1600, 3), bgr(BG), np.uint8)
    draw_chart_static(img, C, (0, 0, 1600, 300))
    draw_chart_live(img, C, (0, 0, 1600, 300))
    cv2.imwrite(str(out / "gap.png"), img)


# ---------------------------------------------------------------- video

def layout(pic_w, pic_h):
    """Two panels side by side (picture aspect kept), label band above, gap chart below."""
    pw = 932
    ph = pw * pic_h / pic_w
    if ph > 700:
        ph, pw = 700, 700 * pic_w / pic_h
    pw, ph = int(pw) & ~1, int(ph) & ~1
    y = 96
    return dict(pw=pw, ph=ph, xa=W // 2 - 10 - pw, xb=W // 2 + 10, y=y,
                chart=(48, y + ph + 20, W - 96, H - (y + ph + 20) - 20))


def cut_panel(meta, lap, lead_f, n, L, dst, audio):
    """Frame-accurate cut of one lap's footage, cropped to its picture and scaled into its panel; frames
    before the video start / after its end are held (lap near the edge of a recording)."""
    fps = meta["fps"]
    first = lap["start"] - lead_f
    pre, post = max(0, -first), max(0, first + n - meta["n"])
    x0, y0, x1, y1 = meta["pic_box"]
    vf = (f"crop={x1 - x0}:{y1 - y0}:{x0}:{y0},scale={L['pw']}:{L['ph']}:force_original_aspect_ratio=decrease,"
          f"pad={L['pw']}:{L['ph']}:(ow-iw)/2:(oh-ih)/2,setsar=1")
    if pre or post:
        vf += f",tpad=start_mode=clone:start_duration={pre / fps:.4f}:stop_mode=clone:stop_duration={post / fps:.4f}"
    cmd = [ffmpeg_exe(), "-loglevel", "error", "-y", "-ss", f"{max(first, 0) / fps:.6f}", "-i", meta["video"],
           "-vf", vf, "-frames:v", str(n), "-c:v", "libx264", "-preset", "fast", "-crf", "14", "-pix_fmt", "yuv420p",
           "-r", f"{fps:g}", "-g", str(int(round(fps)))]                # keyframe every second: HyperFrames seeks
    if audio:
        cmd += ["-t", f"{n / fps:.6f}", "-c:a", "aac", "-b:a", "160k"]
        if pre:
            cmd += ["-af", f"adelay={int(pre / fps * 1000)}:all=1"]
    else:
        cmd += ["-an"]
    subprocess.run(cmd + ["-movflags", "+faststart", str(dst)], check=True)


def plan_video(C, lead):
    fps = C["fps"]
    lead_f = int(round(lead * fps))
    longest = max(C["a"]["end"] - C["a"]["start"], C["b"]["end"] - C["b"]["start"])
    return dict(fps=fps, lead=lead_f / fps, lead_f=lead_f, n=longest + 2 * lead_f + 1)


def clock(t, P, X):
    """Lap clock of lap X at clip time t: 0 before its gate, frozen on the lap time after the finish."""
    return min(max(t - P["lead"], 0.0), X["time"])


def render_opencv(C, P, L, clips, out, audio_clip):
    fps, n = P["fps"], P["n"]
    ff = subprocess.Popen([ffmpeg_exe(), "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
                           "-s", f"{W}x{H}", "-r", f"{fps:g}", "-i", "-",
                           *(["-i", str(audio_clip), "-map", "0:v", "-map", "1:a?", "-c:a", "copy"] if audio_clip else []),
                           "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
                           "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)
    caps = [cv2.VideoCapture(str(c)) for c in clips]
    base = np.full((H, W, 3), bgr(BG), np.uint8)
    for X, x, col, tag in ((C["a"], L["xa"], COL_A, "A"), (C["b"], L["xb"], COL_B, "B")):
        cv2.rectangle(base, (x, 28), (x + 34, 62), bgr(col), -1)
        _text(base, tag, (x + 8, 55), 0.85, BG, 2)
        _text(base, X["label"], (x + 48, 50), 0.68, INK, 1)
        _text(base, " · ".join(s for s in (X["short"], X["role"]) if s), (x + 48, 80), 0.5, MUTED, 1)
    draw_chart_static(base, C, L["chart"])
    last = [None, None]
    for i in range(n):
        t = i / fps
        img = base.copy()
        for k, (cap, x) in enumerate(zip(caps, (L["xa"], L["xb"]))):
            ok, fr = cap.read()
            if ok:
                last[k] = fr
            if last[k] is not None:
                img[L["y"]:L["y"] + L["ph"], x:x + L["pw"]] = last[k][:L["ph"], :L["pw"]]
        for X, x, col in ((C["a"], L["xa"], COL_A), (C["b"], L["xb"], COL_B)):
            c = clock(t, P, X)
            fin = c >= X["time"]
            y1 = L["y"] + L["ph"] - 16
            ov = img[y1 - 64:y1, x + 16:x + 260].copy()
            img[y1 - 64:y1, x + 16:x + 260] = cv2.addWeighted(ov, 0.22, np.full_like(ov, (14, 10, 8)), 0.78, 0)
            cv2.rectangle(img, (x + 16, y1 - 64), (x + 20, y1), bgr(col), -1)
            _text(img, f"{c:.2f}s", (x + 34, y1 - 16), 1.45, "#ffd21f" if fin else INK, 2)
        draw_chart_live(img, C, L["chart"], clock(t, P, C["a"]))
        ff.stdin.write(img.tobytes())
    ff.stdin.close()
    ff.wait()
    for c in caps:
        c.release()


def render_hyperframes(C, P, L, clips, out, audio_k, proj):
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "assets" / "fonts").mkdir(parents=True, exist_ok=True)
    for f in (ASSETS / "overlay" / "fonts").iterdir():
        shutil.copy(f, proj / "assets" / "fonts" / f.name)
    for k, c in enumerate(clips):
        shutil.copy(c, proj / "assets" / f"lap_{'ab'[k]}.mp4")
    G = chart_geometry(C, L["chart"])
    ts = np.arange(len(C["curve"])) / C["curve_hz"]
    S = C["sectors"]
    edges = [0.0] + S["edges_a_s"] + [C["a"]["time"]]
    data = dict(lead=P["lead"], layout=L, chart=L["chart"],
                a=dict(label=C["a"]["label"], sub=" · ".join(s for s in (C["a"]["short"], C["a"]["role"]) if s),
                       time=C["a"]["time"]),
                b=dict(label=C["b"]["label"], sub=" · ".join(s for s in (C["b"]["short"], C["b"]["role"]) if s),
                       time=C["b"]["time"]),
                curve=C["curve"], hz=C["curve_hz"],
                path=" ".join(f"{G['X'](tt)},{G['Y'](g)}" for tt, g in zip(ts, C["curve"])),
                zero=G["Y"](0), ymid=(G["py0"] + G["py1"]) / 2, yscale=(G["py1"] - G["py0"]) / 2 / G["m"], px0=G["px0"], px1=G["px1"], py0=G["py0"], py1=G["py1"],
                ticks=[dict(y=G["Y"](v), v=v) for v in _ticks(G["m"])],
                sectors=[dict(x0=G["X"](edges[k]), x1=G["X"](edges[k + 1]), end=edges[k + 1], delta=S["delta"][k])
                         for k in range(len(edges) - 1)],
                area_pos=area_path(C, G, 1), area_neg=area_path(C, G, -1))
    html = (ASSETS / "compare" / "index.html").read_text()
    dur = f"{P['n'] / P['fps']:.3f}"
    for key, val in {"__W__": str(W), "__H__": str(H), "__FPS__": f"{P['fps']:g}", "__DURATION__": dur,
                     "__DATA__": json.dumps(data),       # one lap's audio (or none): the other video is muted
                     "__AUDIO_A__": 'data-has-audio="true" data-volume="1"' if audio_k == 0 else "muted",
                     "__AUDIO_B__": 'data-has-audio="true" data-volume="1"' if audio_k == 1 else "muted"}.items():
        html = html.replace(key, val)
    (proj / "index.html").write_text(html)
    cmd = ["npx", "--yes", HYPERFRAMES, "render", str(proj), "-f", f"{P['fps']:g}", "-q", "delivery", "-o", str(out)]
    subprocess.run(cmd, check=True, env=env_with_tools())


def area_path(C, G, sign):
    """SVG path of the area between the gap curve and zero on one side (sign +1: A behind)."""
    ts = np.arange(len(C["curve"])) / C["curve_hz"]
    g = np.array(C["curve"]) * sign
    pts = [f"M{G['X'](0)},{G['Y'](0)}"]
    for tt, v in zip(ts, g):
        pts.append(f"L{G['X'](tt)},{G['Y'](max(v, 0) * sign)}")
    pts.append(f"L{G['X'](ts[-1])},{G['Y'](0)}Z")
    return "".join(pts)


def compare(work=None, laps=None, work_root="fpvlaps-work", renderer="auto", audio="a", lead=1.0, video=True,
            log=print):
    if laps:
        if len(laps) != 2:
            raise SystemExit("give exactly two --lap (or none for the default pair, with --work)")
        A, B = (parse_lap(s, work, work_root) for s in laps)
    else:
        if not work:
            raise SystemExit("give --work (default pair: its best lap vs the best on the track) or two --lap")
        A, B = default_pair(work, work_root, log)
    if A["work"] == B["work"] and A["lap"]["start"] == B["lap"]["start"] and A["lap"]["video"] == B["lap"]["video"]:
        raise SystemExit("both --lap point at the same lap")
    C, _ = compare_laps(A, B, log)
    out = out_dir(A, B)
    out.mkdir(parents=True, exist_ok=True)
    write_png(out, C)
    mp4 = None
    if video:
        mp4 = render_video(C, A, B, out, renderer, audio, lead, log)
        C["video"] = dict(output=str(mp4), audio=audio)
    (out / "compare.json").write_text(json.dumps(C, indent=1))
    write_md(out, C, mp4)
    log(f"  comparison: {out / 'compare.md'}")
    return out


def render_video(C, A, B, out, renderer, audio, lead, log):
    ma, _ = features(A["work"], A["lap"]["video"])
    mb, _ = features(B["work"], B["lap"]["video"])
    for m in (ma, mb):
        if not Path(m["video"]).is_file():
            raise SystemExit(f"Recording {m['video']} not found (needed for the video; --no-video skips it)")
    x0, y0, x1, y1 = ma["pic_box"]
    L = layout(x1 - x0, y1 - y0)
    P = plan_video(C, lead)
    audio_k = {"a": 0, "b": 1}.get(audio)
    clips = [out / "lap_a.mp4", out / "lap_b.mp4"]
    for k, (m, X) in enumerate(((ma, A), (mb, B))):
        cut_panel(m, X["lap"], P["lead_f"], P["n"], L, clips[k], audio_k == k)
    # auto = OpenCV: same layout, ~40 s for a 15 s clip; HyperFrames (two videos + an SVG chart in a
    # 1080p page) took ~15 min here, so it is used only when asked for
    use = "opencv" if renderer == "auto" else renderer
    if use == "hyperframes" and not hyperframes_ready():
        raise SystemExit("HyperFrames needs npx + ffmpeg + ffprobe on PATH; use --renderer opencv")
    mp4 = out / f"compare_{C['a']['video']}_{C['a']['time']:.2f}s_vs_{C['b']['video']}_{C['b']['time']:.2f}s.mp4"
    if use == "hyperframes":
        render_hyperframes(C, P, L, clips, mp4, audio_k, out / "hyperframes")
    else:
        render_opencv(C, P, L, clips, mp4, clips[audio_k] if audio_k is not None else None)
    for c in clips:
        c.unlink(missing_ok=True)
    log(f"  exported {mp4}  ({use}, audio: {'none' if audio_k is None else 'lap ' + audio.upper()})")
    return mp4
