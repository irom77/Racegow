"""OSD timer layouts: the default HDZero layout must stay exactly as it was; wider pitches only add."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fpvlaps import osd  # noqa: E402


class TestLayouts(unittest.TestCase):
    def test_default_layout_unchanged(self):
        self.assertEqual(osd.digit_dx((1041.6, 461.1, 18.0)), (-70.5, -38.5, 25.5, 57.5))

    def test_pitch_32_formula_matches_default(self):
        self.assertEqual(osd.digit_dx((0, 0, 18.1, 32.0)), osd.DIGIT_DX)

    def test_wide_layout(self):
        # 40 px characters, centred 2.5 px right of the colon: digits at -80, -40, +40, +80
        dx = osd.digit_dx((1063.0, 677.0, 18.1, 40.0))
        self.assertEqual([d + osd.CELL_W / 2 - 2.5 for d in dx], [-80, -40, 40, 80])
        boxes = osd.cell_boxes((1063.0, 677.0, 18.1, 40.0))
        self.assertEqual([b[0] for b in boxes], [974, 1014, 1094, 1134])


class TestThinFont(unittest.TestCase):
    def test_thin_boxes(self):
        # MultiGP Tritac 2026-11-01, hdz_0028 frame 3000 ("00:25"): colon at x 1157, glyph lefts
        # 1101 / 1125 / 1174 / 1198, 15 px tall from y 475
        boxes = osd.cell_boxes((1157.0, 482.0, 6.0, 0.0, osd.THIN))
        self.assertEqual([b[0] + 2 for b in boxes], [1101, 1125, 1174, 1198])
        self.assertTrue(all(b[1] <= 475 and b[1] + b[3] >= 490 for b in boxes))

    def test_thin_not_confused_with_wide(self):
        self.assertTrue(osd.is_thin((1, 2, 6, 0.0, osd.THIN)))
        self.assertFalse(osd.is_thin((1, 2, 18.1, 40.0)))
        self.assertFalse(osd.is_thin((1, 2, 18.1)))

    def test_thin_colon_follows_jitter(self):
        g = np.zeros((720, 1280), np.uint8)
        g[480:483, 1159:1162] = 255                                  # dots 2 px right of calibration
        g[486:489, 1159:1162] = 255
        cx, cy = osd.thin_colon_here(g, (1158.0, 485.5, 6.0, 0.0, osd.THIN))[:2]
        self.assertAlmostEqual(cx, 1160.0)
        self.assertAlmostEqual(cy, 484.0)


class TestRunsForward(unittest.TestCase):
    def test_timer_with_misreads(self):
        # RealSco's upload sampled across the video: a ticking timer with OCR misreads (0 read as 3)
        secs = np.array([3, 1, 32, np.nan, 4, 34, 5, 5, 7, 7, 5, 35, 10, 11, 11, 12, np.nan, 14, 14, 15, 16,
                         19, 23, 22, 24, 25, 25, 25, 1827, 20, 20, 25, 30, 1831, 32, 32, 33, 2014, 35, 35], float)
        self.assertTrue(osd.runs_forward(secs))

    def test_fluctuating_value_is_not_a_timer(self):
        lq = 1680 + np.random.default_rng(0).integers(0, 10, 40)    # e.g. link quality "28:100"
        self.assertFalse(osd.runs_forward(lq.astype(float)))

    def test_frozen_or_unreadable(self):
        self.assertFalse(osd.runs_forward(np.full(20, 5.0)))
        self.assertFalse(osd.runs_forward(np.array([np.nan] * 10 + [1, 2])))


if __name__ == "__main__":
    unittest.main()
