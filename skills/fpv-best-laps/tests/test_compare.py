"""Side-by-side lap comparison: lap specs, the default pair, the running gap and sector deltas.

    python -m unittest discover -s skills/fpv-best-laps/tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fpvlaps.compare import (compare_laps, default_pair, describe, draw_chart_live, draw_chart_static,  # noqa: E402
                             gap_curve, layout, load_result, parse_lap, write_md)

FPS = 60.0
N_COURSE = 600                                     # course positions = frames of a 10 s lap at 60 fps


def course_images(seed=0, keys=24):
    """Thumbnail at every course position: smooth blends between random low-frequency pictures."""
    rng = np.random.default_rng(seed)
    base = [cv2.resize(rng.uniform(0, 255, (6, 8, 3)).astype(np.float32), (80, 60), interpolation=cv2.INTER_CUBIC)
            for _ in range(keys + 1)]
    out = []
    for p in range(N_COURSE):
        u = p / N_COURSE * keys
        k, f = int(u), u - int(u)
        out.append((1 - f) * base[k] + f * base[k + 1])
    return np.clip(out, 0, 255).astype(np.uint8)


def fly(imgs, speeds, pad=60):
    """Thumbs of one lap flown at the given speed per third of the course, with `pad` still frames each side.
    Returns (thumbs, lap start, lap end)."""
    idx, pos = [0.0] * pad, 0.0
    while pos < N_COURSE:
        idx.append(pos)
        pos += speeds[min(int(pos / (N_COURSE / 3)), 2)]
    start, end = pad, len(idx)
    idx += [N_COURSE - 1] * pad
    return imgs[np.clip(np.round(idx).astype(int), 0, N_COURSE - 1)], start, end


def lap(video, start, end, clean=True, **kw):
    return dict(video=video, start=start, end=end, time=round((end - start) / FPS, 3), clean=clean,
                reason="" if clean else "off-line", cost=0.3, **kw)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.works = self.root / "works"

    def tearDown(self):
        self.tmp.cleanup()

    def session(self, name, laps, videos_dir=None, thumbs=None, **extra):
        d = self.works / name
        (d / "features").mkdir(parents=True, exist_ok=True)
        R = dict(fps=FPS, videos_dir=str(videos_dir) if videos_dir else None, laps=laps, best=[],
                 reference=dict(video="v1", start=0, end=600), **extra,
                 videos=[dict(name=v, path=str(d / f"{v}.mp4"), seconds=100.0) for v in sorted({l["video"] for l in laps})])
        (d / "result.json").write_text(json.dumps(R))
        for v, th in (thumbs or {}).items():
            np.save(d / "features" / f"{v}.thumbs.npy", th)
            (d / "features" / f"{v}.json").write_text(json.dumps(dict(video=str(d / f"{v}.mp4"), name=v, fps=FPS,
                                                                       n=len(th), pic_box=[0, 0, 80, 60])))
        return d


class Specs(Base):
    def setUp(self):
        super().setUp()
        self.s1 = self.session("Track2-1st", [lap("hdz_0001", 100, 700), lap("hdz_0001", 700, 1260),
                                              lap("hdz_0001", 1260, 1800, clean=False), lap("hdz_0002", 0, 650)])
        self.s2 = self.session("Track2-2nd", [lap("hdz_0001", 50, 600)])

    def test_forms(self):
        p = parse_lap("Track2-1st/hdz_0001:2", work_root=self.works)
        self.assertEqual((p["lap"]["start"], p["number"]), (700, 2))
        self.assertEqual(parse_lap("Track2-1st/hdz_0001", work_root=self.works)["lap"]["start"], 700)   # best clean
        self.assertEqual(parse_lap("Track2-1st/hdz_0001@21.5", work_root=self.works)["lap"]["start"], 1260)
        self.assertEqual(parse_lap("hdz_0002.mp4:1", work_root=self.works)["session"], "Track2-1st")
        self.assertEqual(parse_lap("hdz_0001:1", work=self.s2, work_root=self.works)["lap"]["start"], 50)
        self.assertIn("hdz_0001 @ 11.7s", parse_lap(f"{self.s1}/hdz_0001:2")["label"])

    def test_errors(self):
        with self.assertRaises(SystemExit):
            parse_lap("hdz_0001:1", work_root=self.works)               # in two sessions: ambiguous
        with self.assertRaises(SystemExit):
            parse_lap("Track2-1st/hdz_0001:9", work_root=self.works)
        with self.assertRaises(SystemExit):
            parse_lap("Track2-1st/hdz_0009", work_root=self.works)


class DefaultPair(Base):
    def test_best_here_vs_best_on_track(self):
        track = self.root / "Track2"
        for b in ("1st", "2nd"):
            (track / b).mkdir(parents=True)
        (track / "README.md").write_text("# Track 2\n")
        old = self.session("old", [lap("hdz_0001", 0, 540), lap("hdz_0001", 540, 1150)], videos_dir=track / "1st")
        new = self.session("new", [lap("hdz_0005", 0, 570), lap("hdz_0005", 570, 1200)], videos_dir=track / "2nd")
        self.session("other", [lap("hdz_0009", 0, 300)], videos_dir=self.root / "Track1" / "1st")
        A, B = default_pair(new, self.works, log=lambda *a: None)
        self.assertEqual((A["lap"]["start"], A["role"]), (0, "best lap this session"))
        self.assertEqual((B["session"], B["lap"]["start"], B["role"]), ("old", 0, "best lap on the track"))
        A, B = default_pair(old, self.works, log=lambda *a: None)          # old holds the track best
        self.assertEqual((B["session"], B["lap"]["start"], B["role"]), ("new", 0, "next fastest lap on the track"))


class Gap(Base):
    def setUp(self):
        super().setUp()
        imgs = course_images()
        self.ta, self.a0, self.a1 = fly(imgs, (1.0, 1.0, 1.0))           # 10 s, even pace
        self.tb, self.b0, self.b1 = fly(imgs, (1.25, 1.0, 0.8))          # B: faster in S1, slower in S3

    def test_gap_curve(self):
        from fpvlaps.laps import dtw_desc
        XA, XB = dtw_desc(self.ta[self.a0:self.a1 + 1]), dtw_desc(self.tb[self.b0:self.b1 + 1])
        nA, nB = self.a1 - self.a0, self.b1 - self.b0
        gap, posB = gap_curve(XA, XB, nA, nB, FPS)
        self.assertEqual(len(gap), nA + 1)
        self.assertAlmostEqual(gap[0], 0, places=6)
        self.assertAlmostEqual(gap[-1], (nA - nB) / FPS, places=6)
        # after S1 (200 course frames) A is 200 - 200/1.25 = 40 frames behind
        self.assertAlmostEqual(gap[200], 40 / FPS, delta=0.1)
        self.assertTrue(np.all(np.diff(posB) >= 0))

    def test_compare_laps_and_outputs(self):
        sa = self.session("s1", [lap("va", self.a0, self.a1)], thumbs={"va": self.ta})
        sb = self.session("s2", [lap("vb", self.b0, self.b1)], thumbs={"vb": self.tb})
        A = describe(sa, load_result(sa), load_result(sa)["laps"][0])
        B = describe(sb, load_result(sb), load_result(sb)["laps"][0])
        C, gap = compare_laps(A, B, log=lambda *a: None)
        S = C["sectors"]
        self.assertIn("even split", S["source"])
        want = [200 / FPS - 160 / FPS, 0.0, 200 / FPS - 250 / FPS]           # A - B per third
        for got, exp in zip(S["delta"], want):
            self.assertAlmostEqual(got, exp, delta=0.12)
        self.assertAlmostEqual(sum(S["delta"]), C["final_gap"], places=2)
        self.assertAlmostEqual(C["curve"][-1], C["final_gap"], places=3)
        self.assertEqual([m["kind"] for m in C["moments"]], ["loss", "gain"])
        out = self.root / "out"
        out.mkdir()
        write_md(out, C)
        md = (out / "compare.md").read_text()
        self.assertIn("| S3 |", md)
        self.assertIn("A furthest behind", md)
        L = layout(960, 720)
        self.assertEqual((L["pw"], L["ph"]), (932, 698))
        img = np.zeros((1080, 1920, 3), np.uint8)
        draw_chart_static(img, C, L["chart"])
        draw_chart_live(img, C, L["chart"], 5.0)
        self.assertGreater(img[L["chart"][1]:, :].mean(), 1)

    def test_both_sector_splits(self):
        """Both laps timed against the same reference: lap B's own boundaries are used as they are."""
        sec = dict(boundaries=[200, 400])
        sa = self.session("s1", [lap("va", self.a0, self.a1, sector_frames=[self.a0 + 200, self.a0 + 400])],
                          thumbs={"va": self.ta}, sectors=sec)
        sb = self.session("s2", [lap("vb", self.b0, self.b1, sector_frames=[self.b0 + 160, self.b0 + 360])],
                          thumbs={"vb": self.tb}, sectors=sec)
        A = describe(sa, load_result(sa), load_result(sa)["laps"][0])
        B = describe(sb, load_result(sb), load_result(sb)["laps"][0])
        C, _ = compare_laps(A, B, log=lambda *a: None)
        self.assertIn("both laps", C["sectors"]["source"])
        self.assertEqual(C["sectors"]["b"][:2], [round(160 / FPS, 3), round(200 / FPS, 3)])


if __name__ == "__main__":
    unittest.main()
