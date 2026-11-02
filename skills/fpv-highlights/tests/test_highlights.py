import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fpvhl.pick import parse_ranges, to_s, select, interest, sample_masks  # noqa: E402
from fpvhl.render import check_save_dir, default_save_dir  # noqa: E402
from fpvhl.scan import static_text  # noqa: E402
from fpvhl.youtube import flown_date  # noqa: E402


def fake_video(seconds, active=None, color=(80, 120, 160), osd=None):
    """10 Hz features: moving (diff 10, some flow) inside `active` (list of (a, b) s), parked elsewhere."""
    m = int(seconds * 10)
    F = np.zeros((m, 9), np.float32)
    F[:, 4] = 1.5                      # parked: sensor noise only
    F[:, 5:8] = (120, 40, 0.95)        # good picture
    for a, b in active or [(0, seconds)]:
        s, e = int(a * 10), int(b * 10)
        F[s:e, 0] = 2.0
        F[s:e, 1] = 0.02
        F[s:e, 3] = 1.0
        F[s:e, 4] = 12.0
    for a, b in osd or []:
        F[int(a * 10):int(b * 10), 8] = 0.04
    thumbs = np.zeros((int(seconds) + 1, 72, 128, 3), np.uint8)
    thumbs[:] = color
    thumbs[:, :36] = (color[2], color[0], color[1])
    return dict(path=f"/x/{seconds}.ts", fps=60.0, step=6, dt=0.1, feats=F, audio=np.zeros(m, np.float32),
                thumbs=thumbs)


class TestRanges(unittest.TestCase):
    def test_parse(self):
        r = parse_ranges("hdz_030, hdz_031:12-40.5,hdz_031.ts:1:05-1:10")
        self.assertEqual(r["hdz_030"], [(0.0, float("inf"))])
        self.assertEqual(r["hdz_031"], [(12.0, 40.5), (65.0, 70.0)])
        self.assertEqual(to_s("2:03.5"), 123.5)

    def test_bad_spec(self):
        with self.assertRaises(SystemExit):
            parse_ranges("hdz_030:abc")


class TestSelect(unittest.TestCase):
    def vids(self):
        return {"a": fake_video(60, [(5, 50)], (200, 60, 60)), "b": fake_video(60, [(5, 50)], (60, 200, 60)),
                "c": fake_video(60, [(5, 50)], (60, 60, 200))}

    def test_budget_and_cap(self):
        v = self.vids()
        interest(v)
        picked, _ = select(v, length=20, clip=4, per_video=1)
        self.assertLessEqual(sum(p["end"] - p["start"] for p in picked), 20.001)
        self.assertEqual(len({p["video"] for p in picked}), len(picked))   # one per recording

    def test_never_parked_or_stats(self):
        v = {"a": fake_video(80, [(10, 30), (40, 70)], osd=[(40, 70)])}
        interest(v)
        picked, _ = select(v, length=60, clip=4, per_video=5)
        self.assertTrue(picked)
        for p in picked:
            self.assertGreaterEqual(p["start"], 10 - 1e-6)
            self.assertLessEqual(p["end"], 30 + 1e-6)

    def test_exclude_include(self):
        v = self.vids()
        interest(v)
        picked, _ = select(v, length=30, clip=4, per_video=2, exclude="a,b:0-60", include="c:10-14")
        self.assertTrue(all(p["video"] == "c" for p in picked))
        self.assertTrue(picked[0]["forced"] or any(p["forced"] for p in picked))

    def test_hook_order(self):
        v = self.vids()
        v["b"]["feats"][200:300, 1] = 0.08          # b has the best rolls
        interest(v)
        picked, _ = select(v, length=30, clip=4, per_video=1, order="hook")
        self.assertEqual(picked[0]["video"], "b")
        rest = [(p["video"], p["start"]) for p in picked[1:]]
        self.assertEqual(rest, sorted(rest))

    def test_masks(self):
        F = fake_video(10, [(0, 5)])["feats"]
        F[60:, 7] = 0.2                              # static noise
        bad, still = sample_masks(F)
        self.assertTrue(bad[70] and not bad[20])
        self.assertTrue(still[90] and not still[20])


class TestStaticText(unittest.TestCase):
    def test_text_vs_motion(self):
        rng = np.random.default_rng(0)
        a = rng.integers(0, 255, (160, 320), dtype=np.uint8)
        b = rng.integers(0, 255, (160, 320), dtype=np.uint8)
        a[40:120, 60:260:8] = 255
        b[40:120, 60:260:8] = 255
        a[40:120, 61:261:8] = 0
        b[40:120, 61:261:8] = 0
        self.assertGreater(static_text(a, b), 0.02)
        c = rng.integers(0, 255, (160, 320), dtype=np.uint8)
        self.assertLess(static_text(c, rng.integers(0, 255, (160, 320), dtype=np.uint8)), 0.02)


class TestSaveAndDate(unittest.TestCase):
    def test_save_dir(self):
        with TemporaryDirectory() as t:
            rec = Path(t) / "Videos" / "HDZero_12_16_2024"
            rec.mkdir(parents=True)
            self.assertEqual(default_save_dir(rec), Path(t) / "Videos" / "fpv-shorts" / "HDZero_12_16_2024")
            check_save_dir(default_save_dir(rec), rec)
            for bad in (rec, rec / "shorts"):
                with self.assertRaises(SystemExit):
                    check_save_dir(bad, rec)

    def test_date_from_folder(self):
        self.assertEqual(flown_date("/v/HDZero_12_16_2024", [])[0], "2024-12-16")
        self.assertEqual(flown_date("/v/2025-06-01 park", [])[0], "2025-06-01")
        self.assertEqual(flown_date("/v/misc", [])[0], None)


if __name__ == "__main__":
    unittest.main()
