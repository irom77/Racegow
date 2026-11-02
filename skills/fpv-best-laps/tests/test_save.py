import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fpvlaps.render import check_save_dir, save_copies  # noqa: E402


class TestSaveTo(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        t = Path(self.tmp.name)
        self.rec = t / "Videos" / "HDZero_11_01_2026"
        self.rec.mkdir(parents=True)
        (self.rec / "hdz_0028.mp4").write_bytes(b"x")
        self.work = t / "work"
        (self.work / "export").mkdir(parents=True)
        clip = self.work / "export" / "best3_laps_hdz_0028_107.07s.mp4"
        clip.write_bytes(b"clip")
        (self.work / "export" / "render_rank1.json").write_text(json.dumps({"output": str(clip)}))
        self.R = dict(videos_dir=str(self.rec), videos=[dict(name="hdz_0028", path=str(self.rec / "hdz_0028.mp4"))])
        (self.work / "result.json").write_text(json.dumps(self.R))

    def tearDown(self):
        self.tmp.cleanup()

    def test_refuses_recordings_folder_and_below(self):
        for d in (self.rec, self.rec / "shorts"):
            with self.assertRaises(SystemExit):
                check_save_dir(d, self.R)

    def test_refuses_video_parent_without_videos_dir(self):
        with self.assertRaises(SystemExit):
            check_save_dir(self.rec, dict(videos=self.R["videos"]))

    def test_sibling_folder_ok_and_copied(self):
        dest = self.rec.parent / "fpv-shorts" / "Tritac-R1"
        out = save_copies(self.work, dest)
        self.assertEqual([p.name for p in out], ["best3_laps_hdz_0028_107.07s.mp4"])
        self.assertEqual(out[0].read_bytes(), b"clip")


if __name__ == "__main__":
    unittest.main()
