"""Sector splits: spec parsing, DTW boundary mapping, sector times and the theoretical best.

    python -m unittest discover -s skills/fpv-best-laps/tests"""
import sys
import unittest
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fpvlaps.config import DTW_STEP, REFINE_WINDOW  # noqa: E402
from fpvlaps.sectors import align, boundaries, parse_spec, sector_lines, split  # noqa: E402


def norm(a):
    a = a - a.mean(-1, keepdims=True)
    return a / (a.std(-1, keepdims=True) + 1e-6)


def smooth_walk(rng, n, d=64):
    """Slowly changing descriptors, like a flight: neighbours similar, far frames different."""
    x = np.cumsum(rng.normal(size=(n, d)), 0)
    return norm(x).astype(np.float32)


class Spec(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_spec("4"), ("even", 4))
        self.assertEqual(parse_spec("3800, 4100"), ("frames", [3800, 4100]))
        with self.assertRaises(SystemExit):
            parse_spec("4100,3800")

    def test_boundaries(self):
        ref = dict(video="v", start=1000, end=1900)
        self.assertEqual(boundaries(ref), ([1300, 1600], "even split"))
        self.assertEqual(boundaries(ref, "2"), ([1450], "--sectors"))
        self.assertEqual(boundaries(dict(ref, sectors=[1200]))[0], [1200])
        with self.assertRaises(SystemExit):
            boundaries(ref, "900,1500")


class Align(unittest.TestCase):
    def test_slower_lap_maps_proportionally(self):
        rng = np.random.default_rng(1)
        T = smooth_walk(rng, 200)
        X = T[np.clip(np.round(np.arange(300) / 1.5).astype(int), 0, 199)]     # same lap, 1.5x slower
        path = align(X, T)
        for m in (50, 100, 150):
            self.assertAlmostEqual(path[m], m * 1.5, delta=2)
        self.assertEqual(path[0], 0)
        self.assertAlmostEqual(path[-1], 299, delta=1)

    def test_impossible_ratio(self):
        rng = np.random.default_rng(2)
        self.assertIsNone(align(smooth_walk(rng, 500), smooth_walk(rng, 100)))


class Split(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(3)
        n_ref = 600                                       # reference lap: 600 frames = 10 s at 60 fps
        ref_f = smooth_walk(rng, n_ref, 32)               # per-frame course descriptors
        pad = 60

        def fly(speeds):
            """A video flying the course once per speed profile (frames per course frame per sector)."""
            idx = [0.0] * pad
            for sp in speeds:
                pos = 0.0
                while pos < n_ref:
                    k = min(int(pos / (n_ref / 3)), 2)
                    idx.append(pos)
                    pos += 1 / sp[k]
            idx += [n_ref - 1] * pad
            F = ref_f[np.clip(np.round(idx).astype(int), 0, n_ref - 1)]
            return F

        self.ref_frames = ref_f
        speeds = [(1, 1, 1), (1.2, 1, 1), (1, 1, 0.8)]   # lap 2 slow in S1, lap 3 fast in S3
        F = fly(speeds)
        starts = [pad]
        for sp in speeds:
            starts.append(starts[-1] + int(round(sum(n_ref / 3 * s for s in sp))))
        self.v = dict(name="v", fps=60.0, F=F, X=F[::DTW_STEP])
        self.laps = [dict(video="v", start=a, end=b, time=(b - a) / 60, cost=0.1, clean=True)
                     for a, b in zip(starts, starts[1:])]
        self.ref = dict(video="v", start=starts[0], end=starts[1])
        self.T = self.v["X"][starts[0] // DTW_STEP:starts[1] // DTW_STEP + 1]

    def test_sector_times(self):
        S = split([self.v], self.laps, self.ref, self.T, log=lambda *a: None)
        self.assertEqual(S["count"], 3)
        want = [[3.33, 3.33, 3.33], [4.0, 3.33, 3.33], [3.33, 3.33, 2.67]]
        for l, w in zip(self.laps, want):
            for got, exp in zip(l["sectors"], w):
                self.assertAlmostEqual(got, exp, delta=0.12)
            self.assertAlmostEqual(sum(l["sectors"]), l["time"], places=2)
        self.assertAlmostEqual(S["theoretical_best"], 3.33 + 3.33 + 2.67, delta=0.2)
        self.assertLess(S["theoretical_best"], min(l["time"] for l in self.laps))

    def test_report_lines(self):
        S = split([self.v], self.laps, self.ref, self.T, log=lambda *a: None)
        R = dict(fps=60.0, laps=self.laps, sectors=S, reference=self.ref,
                 best=[dict(laps=self.laps, total=sum(l["time"] for l in self.laps))])
        text = "\n".join(sector_lines(R))
        self.assertIn("Theoretical best", text)
        self.assertIn("| S1 | S2 | S3 |", text)

    def test_no_clean_laps(self):
        for l in self.laps:
            l["clean"] = False
        self.assertIsNone(split([self.v], self.laps, self.ref, self.T, log=lambda *a: None))


if __name__ == "__main__":
    unittest.main()
