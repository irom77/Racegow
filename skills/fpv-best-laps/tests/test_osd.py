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
