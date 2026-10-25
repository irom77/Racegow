"""Checks that flag a wrong reference lap from the laps timed against it.

    python -m unittest discover -s skills/fpv-best-laps/tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fpvlaps.analyze import reference_problems  # noqa: E402


class ReferenceChecks(unittest.TestCase):
    def test_correct_reference_passes(self):
        self.assertEqual(reference_problems(16.28, 0.86, 16.30), [])     # Track 3, verified lap

    def test_shortcut_loop(self):
        self.assertIn("skips part of the course", reference_problems(11.0, 0.9, 15.6)[0])

    def test_too_long(self):
        # Track 3: reference-video calibration picked a pair 1.23x the lap period
        p = reference_problems(20.12, 0.73, 16.30)
        self.assertEqual(len(p), 1)
        self.assertIn("123%", p[0])

    def test_not_chained(self):
        self.assertIn("share their crossing", reference_problems(16.0, 0.5, 16.3)[0])


if __name__ == "__main__":
    unittest.main()
