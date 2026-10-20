"""Human/agent-readable outputs: report.md, laps.csv and verification contact sheets."""
import csv
import json
from pathlib import Path
import numpy as np
import cv2
from .history import consistency_lines, history_link_for, link_block
from .media import read_frames
from .sectors import sector_lines

OFFSETS = list(range(-24, 13, 6))   # frames around a crossing shown in the sheets


def _tile(fr, box, label, mark=False):
    x0, y0, x1, y1 = box
    im = cv2.resize(fr[y0:y1, x0:x1], (240, 180), interpolation=cv2.INTER_AREA)
    if mark:
        cv2.rectangle(im, (0, 0), (239, 179), (0, 220, 255), 3)
    cv2.putText(im, label, (5, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(im, label, (5, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
    return im


def crossing_sheet(video_path, box, frames, out, title):
    """One row per crossing frame: the frames around it, the crossing itself outlined."""
    rows = []
    for c in frames:
        tiles = []
        want = {c + o: o for o in OFFSETS}
        for f, fr in read_frames(video_path, c + OFFSETS[0], OFFSETS[-1] - OFFSETS[0] + 1):
            if f in want:
                tiles.append(_tile(fr, box, f"{f}" + (" X" if want[f] == 0 else ""), want[f] == 0))
        while len(tiles) < len(OFFSETS):
            tiles.append(np.zeros((180, 240, 3), np.uint8))
        rows.append(np.hstack(tiles))
    head = np.zeros((28, rows[0].shape[1], 3), np.uint8)
    cv2.putText(head, title, (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.imwrite(str(out), np.vstack([head] + rows), [cv2.IMWRITE_JPEG_QUALITY, 85])


def write_reports(work, R, log=print):
    work = Path(work)
    fps = R["fps"]
    vids = {v["name"]: v for v in R["videos"]}
    sheets = work / "sheets"
    sheets.mkdir(exist_ok=True)
    boxes = {n: json.loads((work / "features" / f"{n}.json").read_text())["pic_box"] for n in vids}

    with open(work / "laps.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["video", "start_frame", "end_frame", "start_s", "end_s", "lap_s", "match_cost", "clean", "reason"])
        for l in sorted(R["laps"], key=lambda l: (l["video"], l["start"])):
            w.writerow([l["video"], l["start"], l["end"], f"{l['start'] / fps:.3f}", f"{l['end'] / fps:.3f}",
                        f"{l['time']:.3f}", l["cost"], l["clean"], l["reason"]])

    ref = R["reference"]
    ref_path = vids[ref["video"]]["path"] if ref["video"] in vids else ref.get("path")
    ref_box = boxes.get(ref["video"]) or ref.get("pic_box")
    if ref_path and ref_box and Path(ref_path).exists():
        crossing_sheet(ref_path, ref_box, [ref["start"], ref["end"]], sheets / "reference_lap.jpg",
                       f"Reference lap {ref['video']}: rows = start / end crossing (X). Both rows should show the same spot at the start gate.")
        if R.get("sectors"):
            crossing_sheet(ref_path, ref_box, R["sectors"]["boundaries"], sheets / "sectors.jpg",
                           f"Sector boundaries in the reference lap {ref['video']}: one row per boundary (X) = "
                           "start of S2, S3, ...")
    else:
        log(f"  reference video {ref['video']} not available; skipping reference_lap.jpg")
    for k, b in enumerate(R["best"][:3], 1):
        cs = [b["laps"][0]["start"]] + [l["end"] for l in b["laps"]]
        crossing_sheet(vids[b["video"]]["path"], boxes[b["video"]], cs, sheets / f"rank{k}_crossings.jpg",
                       f"Rank {k}: {b['video']} total {b['total']:.2f}s - each row one gate crossing (X), all rows should match")

    clean = [l for l in R["laps"] if l["clean"]]
    lines = ["# FPV best 3 consecutive laps", ""]
    if R["videos_dir"]:
        lines += [f"Videos: `{R['videos_dir']}` ({len(R['videos'])} files)", ""]
    tr = R.get("track_readme") or {}
    if tr.get("path") or tr.get("reference"):
        lines += ["## Reference to check against", ""]
        if tr.get("path"):
            lines.append(f"- Track README: `{tr['path']}`")
        if tr.get("demo"):
            lines.append(f"- Demo flythrough: {tr.get('demo_link') or tr['demo']}"
                         + (f" (starts at {tr['flythrough']})" if tr.get("flythrough") else "")
                         + ". Fly the winning laps against it gate by gate: the tool only compares laps"
                           " with each other.")
        if tr.get("reference"):
            lines.append(f"- Reference lap chosen from: {tr['reference']}")
        lines.append("")
    if R.get("warnings"):
        lines += ["> **Warning: the reference lap looks wrong.**", ">"] + [f"> {w}" for w in R["warnings"]] + [""]
    if R["best"]:
        b = R["best"][0]
        lines += [f"## Result: {b['total']:.2f}s in `{b['video']}`", "",
                  "| Lap | Time | Frames | Video time |", "|---|---|---|---|"]
        for i, l in enumerate(b["laps"], 1):
            lines.append(f"| {i} | **{l['time']:.2f}s** | {l['start']} -> {l['end']} | "
                         f"{l['start'] / fps:.2f}s -> {l['end'] / fps:.2f}s |")
        lines += [f"| **Total** | **{b['total']:.2f}s** | | |", ""]
        if b.get("warnings"):
            lines += ["**Check before trusting:**", ""] + [f"- {w}" for w in b["warnings"]] + [""]
        lines += ["## Runners-up", "", "| Rank | Video | Total | Laps | Frames | Video time |", "|---|---|---|---|---|---|"]
        for k, r in enumerate(R["best"][1:], 2):
            lines.append(f"| {k} | {r['video']} | {r['total']:.2f}s | "
                         + " / ".join(f"{l['time']:.2f}" for l in r["laps"])
                         + f" | {r['start']} -> {r['end']} | {r['start'] / fps:.2f}s -> {r['end'] / fps:.2f}s |"
                         + (" ⚠ check" if r.get("warnings") else ""))
    else:
        lines += ["## No result", "", "No video contains 3 consecutive clean laps."]
    lines += [""] + sector_lines(R) + consistency_lines(R)
    lines += ["## Session summary", "",
              f"- Lap period (track): {R['lap_period_s']:.2f}s; typical clean lap {R['typical_lap_s']:.2f}s; "
              f"clean laps: {len(clean)} of {len(R['laps'])}; back-to-back laps chained: {R.get('chain_ratio', 1.0):.0%}",
              f"- Reference lap: `{ref['video']}` frames {ref['start']} -> {ref['end']} ({ref['source']})",
              f"- Clean-lap match threshold: {R['clean_cost_threshold']:.3f}", "",
              "| Video | Laps | Clean | Fastest clean | Armed via |", "|---|---|---|---|---|"]
    for v in R["videos"]:
        L = [l for l in R["laps"] if l["video"] == v["name"]]
        C = [l["time"] for l in L if l["clean"]]
        fastest = f"{min(C):.2f}s" if C else "-"
        lines.append(f"| {v['name']} | {len(L)} | {len(C)} | {fastest} | {v['arm_source']} |")
    lines += ["", "Verification sheets: `sheets/reference_lap.jpg`, `sheets/rank1_crossings.jpg` .. `rank3_crossings.jpg`",
              "Every lap: `laps.csv`."]
    lines += [""] + link_block(history_link_for(R))
    (work / "report.md").write_text("\n".join(lines) + "\n")
    log(f"  report: {work / 'report.md'}")
    for w in R.get("warnings", []):
        log(f"  WARNING: {w}")
    if R["best"]:
        b = R["best"][0]
        log(f"  BEST: {b['video']} {b['total']:.2f}s = " + " + ".join(f"{l['time']:.2f}" for l in b["laps"]))
        for w in b.get("warnings", []):
            log(f"  WARNING: {w}")
