"""Extraction: unreadable recordings are skipped, not hung on.

    python -m unittest discover -s skills/fpv-best-laps/tests"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fpvlaps.extract import extract_all  # noqa: E402


class Extract(unittest.TestCase):
    def test_unreadable_video_is_skipped(self):
        # a DVR file cut off before it was finalised has no moov atom: the worker used to exit
        # (SystemExit) and Pool.imap_unordered waited forever for its result
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "hdz_0009.mp4"
            bad.write_bytes(b"\0\0\0\x18ftypmp42" + b"\0" * 4096)
            self.assertEqual(extract_all([bad, bad.with_name("hdz_0011.mp4")], Path(d) / "work", 2), [])
            self.assertEqual(list((Path(d) / "work" / "features").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
