"""Track folder README: parsing, reference precedence and save-track.

    python -m unittest discover -s skills/fpv-best-laps/tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fpvlaps.trackdir import (choose_reference, demo_link, find_readme, parse_clock, parse_readme,  # noqa: E402
                              record_reference_video, save_track)

README = """# Track 2

**Demo video:** https://www.youtube.com/watch?v=PqOFU-AwNvU ("RaceGOW6 Track2 sponsored by BetaFPV and
designed by Sabj")
**Flythrough starts at:** 1:00 (https://www.youtube.com/watch?v=PqOFU-AwNvU&t=60s), runs to 2:40
**Correct lap:** `1st/hdz_0022` at 0:58.98
"""


class TrackDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.track = Path(self.tmp.name) / "Track2"
        for b in ("1st", "2nd"):
            (self.track / b).mkdir(parents=True)
        (self.track / "1st" / "hdz_0022.mp4").write_bytes(b"")
        (self.track / "README.md").write_text(README)

    def tearDown(self):
        self.tmp.cleanup()

    def silent(self, *a):
        pass

    def test_parse_clock(self):
        self.assertEqual(parse_clock("59"), 59)
        self.assertAlmostEqual(parse_clock("0:58.98"), 58.98)
        self.assertEqual(parse_clock("1:02:03"), 3723)

    def test_parse_readme(self):
        info = parse_readme(self.track / "README.md")
        self.assertEqual(info["demo"], "https://www.youtube.com/watch?v=PqOFU-AwNvU")
        self.assertEqual(info["demo_title"], "RaceGOW6 Track2 sponsored by BetaFPV and designed by Sabj")
        self.assertEqual(info["flythrough"], "1:00")
        self.assertEqual(info["correct_lap"]["video"], "1st/hdz_0022")
        self.assertAlmostEqual(info["correct_lap"]["time"], 58.98)
        self.assertEqual(demo_link(info), "https://www.youtube.com/watch?v=PqOFU-AwNvU&t=60s")

    def test_correct_lap_frame_form(self):
        (self.track / "README.md").write_text("**Correct lap:** 1st/hdz_0022.mp4 frame 3539\n")
        lap = parse_readme(self.track / "README.md")["correct_lap"]
        self.assertEqual(lap, dict(video="1st/hdz_0022.mp4", frame=3539))

    def test_correct_lap_frame_range(self):
        (self.track / "README.md").write_text("**Correct lap:** `1st/hdz_0022` frames 1716-2712\n")
        lap = parse_readme(self.track / "README.md")["correct_lap"]
        self.assertEqual(lap, dict(video="1st/hdz_0022", frame=1716, end_frame=2712))
        ch = choose_reference(self.track / "2nd")
        self.assertIsNone(ch["reference_video"])
        self.assertIn("frames 1716-2712", ch["how"])

    def test_correct_lap_video_only_is_reference_video(self):
        (self.track / "README.md").write_text("**Correct lap:** `1st/hdz_0022`\n\nMore notes\n")
        lap = parse_readme(self.track / "README.md")["correct_lap"]
        self.assertEqual(lap, dict(video="1st/hdz_0022"))
        ch = choose_reference(self.track / "2nd")
        self.assertIsNone(ch["correct_lap"])
        self.assertEqual(ch["reference_video"]["path"], (self.track / "1st" / "hdz_0022.mp4").resolve())
        self.assertIn("reference video 1st/hdz_0022", ch["how"])

    def test_reference_video_option(self):
        ch = choose_reference(self.track / "1st", reference_video="hdz_0022")
        self.assertEqual(ch["reference_video"]["video"], "hdz_0022")
        self.assertIsNone(ch["correct_lap"])
        self.assertIn("--reference-video", ch["how"])
        (self.track / "track.json").write_text("{}")         # the command line beats the README's profile
        ch = choose_reference(self.track / "1st", reference_video=str(self.track / "1st" / "hdz_0022.mp4"))
        self.assertIsNone(ch["track"])
        self.assertEqual(ch["reference_video"]["video"], "hdz_0022")
        with self.assertRaises(SystemExit):
            choose_reference(self.track / "1st", reference_video="hdz_9999")

    def test_record_reference_video(self):
        rd = self.track / "README.md"
        rd.write_text("# Track 2\n\n**Demo video:** https://x (\"long\ntitle\")\n**Flythrough starts at:** 1:00\n\nNotes\n")
        self.assertTrue(record_reference_video(rd, self.track / "1st" / "hdz_0022.mp4", self.silent))
        lines = rd.read_text().splitlines()
        self.assertEqual(lines[5], "**Correct lap:** `1st/hdz_0022`")
        self.assertEqual(parse_readme(rd)["correct_lap"], dict(video="1st/hdz_0022"))
        self.assertEqual(parse_readme(rd)["flythrough"], "1:00")
        # never replaces a correct lap that's already there
        self.assertFalse(record_reference_video(rd, self.track / "2nd" / "x.mp4", self.silent))
        rd.write_text(README)
        self.assertFalse(record_reference_video(rd, self.track / "1st" / "hdz_0022.mp4", self.silent))
        self.assertEqual(rd.read_text(), README)

    def test_record_reference_video_demo_only_or_bare(self):
        rd = self.track / "README.md"
        rd.write_text("# Track 2\n**Demo video:** https://x (\"a\nb\")\n\nNotes\n")
        record_reference_video(rd, self.track / "1st" / "hdz_0022.mp4", self.silent)
        self.assertEqual(rd.read_text().splitlines()[3], "**Correct lap:** `1st/hdz_0022`")
        rd.write_text("# Track 2\nnotes\n")
        record_reference_video(rd, self.track / "1st" / "hdz_0022.mp4", self.silent)
        self.assertEqual(rd.read_text().splitlines()[:3], ["# Track 2", "", "**Correct lap:** `1st/hdz_0022`"])
        outside = Path(self.tmp.name) / "other.mp4"
        rd.write_text("# Track 2\n")
        self.assertFalse(record_reference_video(rd, outside, self.silent))

    def test_readme_without_labels(self):
        (self.track / "README.md").write_text("# notes\nnothing here\n")
        self.assertEqual(parse_readme(self.track / "README.md"), {})

    def test_find_readme_in_parent_or_batch(self):
        self.assertEqual(find_readme(self.track / "2nd"), (self.track / "README.md").resolve())
        (self.track / "2nd" / "README.md").write_text("batch notes")
        self.assertEqual(find_readme(self.track / "2nd"), (self.track / "2nd" / "README.md").resolve())
        self.assertIsNone(find_readme(Path(self.tmp.name)))

    def test_find_readme_through_symlinked_batch(self):
        elsewhere = Path(self.tmp.name) / "elsewhere" / "2nd"
        elsewhere.mkdir(parents=True)
        (elsewhere.parent / "README.md").write_text("wrong track")
        link = self.track / "3rd"
        link.symlink_to(elsewhere, target_is_directory=True)
        self.assertEqual(find_readme(link), self.track / "README.md")

    def test_precedence_cli_first(self):
        (self.track / "track.json").write_text("{}")
        ch = choose_reference(self.track / "2nd", track="/x/track.json")
        self.assertEqual(ch["track"], "/x/track.json")
        self.assertIsNone(ch["correct_lap"])
        ch = choose_reference(self.track / "2nd", anchor="hdz_0003:100")
        self.assertEqual(ch["anchor"], "hdz_0003:100")
        self.assertIsNone(ch["track"])

    def test_precedence_track_json_over_correct_lap(self):
        (self.track / "track.json").write_text("{}")
        ch = choose_reference(self.track / "2nd")
        self.assertEqual(ch["track"], str(self.track / "track.json"))
        self.assertIsNone(ch["correct_lap"])
        self.assertEqual(ch["info"]["flythrough"], "1:00")

    def test_precedence_correct_lap(self):
        ch = choose_reference(self.track / "2nd")
        self.assertIsNone(ch["track"])
        self.assertEqual(ch["correct_lap"]["path"], (self.track / "1st" / "hdz_0022.mp4").resolve())
        self.assertIn("track README", ch["how"])

    def test_missing_correct_lap_video(self):
        (self.track / "1st" / "hdz_0022.mp4").unlink()
        with self.assertRaises(SystemExit):
            choose_reference(self.track / "2nd")

    def test_auto_without_readme(self):
        ch = choose_reference(self.track / "2nd", use_readme=False)
        self.assertIsNone(ch["readme"])
        self.assertIsNone(ch["track"])
        self.assertIsNone(ch["correct_lap"])
        self.assertEqual(ch["how"], "automatic calibration")

    def _work(self, **extra):
        work = Path(self.tmp.name) / "work"
        work.mkdir()
        (work / "track.json").write_text('{"new": 1}')
        (work / "track.npz").write_bytes(b"new")
        R = dict(reference=dict(video="1st/hdz_0022", start=3517, end=4348),
                 track_readme=dict(path=str(self.track / "README.md")), track_profile=None)
        R.update(extra)
        (work / "result.json").write_text(json.dumps(R))
        return work

    def test_save_track_to_readme_folder(self):
        dst = save_track(self._work(), log=self.silent)
        self.assertEqual(dst, self.track / "track.json")
        self.assertEqual((self.track / "track.npz").read_bytes(), b"new")

    def test_save_track_never_overwrites_silently(self):
        (self.track / "track.json").write_text('{"verified": 1}')
        (self.track / "track.npz").write_bytes(b"old")
        work = self._work()
        with self.assertRaises(SystemExit):
            save_track(work, log=self.silent)
        self.assertEqual((self.track / "track.json").read_text(), '{"verified": 1}')
        save_track(work, force=True, log=self.silent)
        self.assertEqual((self.track / "track.json.bak").read_text(), '{"verified": 1}')
        self.assertEqual((self.track / "track.npz.bak").read_bytes(), b"old")
        self.assertEqual((self.track / "track.json").read_text(), '{"new": 1}')

    def test_save_track_refuses_reused_profile(self):
        with self.assertRaises(SystemExit):
            save_track(self._work(track_profile="/x/track.json"), log=self.silent)


if __name__ == "__main__":
    unittest.main()
