"""Progress across sessions: per-session stats, track matching, dedup and the report.md link.

    python -m unittest discover -s skills/fpv-best-laps/tests"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fpvlaps.history import collect, consistency_lines, session_stats, set_report_link, write_history  # noqa: E402


def lap(t, clean=True, reason=""):
    return dict(video="hdz_0001", start=0, end=0, time=t, clean=clean, reason=reason)


def result(videos_dir, laps, best=None, readme=None, names=("hdz_0001",)):
    return dict(videos_dir=str(videos_dir), laps=laps, best=[dict(total=best, video="hdz_0001")] if best else [],
                track_readme=dict(path=str(readme)) if readme else None,
                videos=[dict(name=n, path=str(Path(videos_dir) / f"{n}.mp4"), seconds=100.0) for n in names])


class History(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.track = root / "Track2"
        self.works = root / "works"
        for b in ("2026-10-12", "2026-10-19"):
            (self.track / b).mkdir(parents=True)
        (self.track / "README.md").write_text("# Track 2\n")

    def tearDown(self):
        self.tmp.cleanup()

    def silent(self, *a):
        pass

    def save(self, work, R):
        d = self.works / work
        d.mkdir(parents=True, exist_ok=True)
        (d / "result.json").write_text(json.dumps(R))
        (d / "report.md").write_text("# report\n")
        return d

    def test_session_stats(self):
        R = result(self.track, [lap(14.0), lap(15.0), lap(16.0), lap(9.0, False, "implausible duration"),
                                lap(20.0, False, "quad stopped inside the lap (crash)")], best=45.0)
        s = session_stats(R)
        self.assertEqual((s["laps"], s["clean"], s["crashes"]), (5, 3, 1))
        self.assertEqual((s["best_lap"], s["median_lap"], s["gap_lap"], s["best3"]), (14.0, 15.0, 1.0, 45.0))
        self.assertAlmostEqual(s["std_lap"], 1.0)
        self.assertAlmostEqual(s["clean_pct"], 60.0)
        self.assertAlmostEqual(s["bad_pct"], 40.0)
        self.assertIn("3 of 5 (60%)", "\n".join(consistency_lines(R)))

    def test_no_clean_laps(self):
        s = session_stats(result(self.track, [lap(9.0, False, "disarmed during lap")]))
        self.assertIsNone(s["best_lap"])
        self.assertIsNone(s["best3"])

    def test_collect_matches_track_by_folder_and_name(self):
        self.save("a", result(self.track / "2026-10-19", [lap(14.0)], names=("hdz_0002",)))
        self.save("Track2-old", result("/gone/batch1", [lap(15.0)], names=("hdz_0003",)))   # name in work dir
        self.save("b", result(self.track / "2026-10-12", [lap(16.0)], readme=self.track / "README.md"))
        self.save("t20", result("/x/Track20/1st", [lap(13.0)], names=("hdz_0004",)))           # not Track2
        self.save("other", result("/x/Track1/1st", [lap(13.0)], names=("hdz_0005",)))
        sessions, folder = collect(str(self.track), self.works, self.silent)
        self.assertEqual(folder, Path(os.path.realpath(self.track)))
        self.assertEqual(sorted(Path(s["work"]).name for s in sessions), ["Track2-old", "a", "b"])
        dated = [s for s in sessions if s["date_source"] == "folder name"]
        self.assertEqual([s["date"] for s in dated], ["2026-10-12", "2026-10-19"])      # oldest first
        by_name, _ = collect("Track2", self.works, self.silent)
        self.assertEqual(len(by_name), 3)

    def test_same_footage_counts_once(self):
        old = self.save("old", result(self.track / "2026-10-12", [lap(16.0)]))
        time.sleep(0.01)
        self.save("new", result(self.track / "2026-10-12", [lap(15.0)]))
        os.utime(old / "result.json", (1, 1))
        sessions, _ = collect(str(self.track), self.works, self.silent)
        self.assertEqual([Path(s["work"]).name for s in sessions], ["new"])

    def test_report_link_is_idempotent(self):
        rep = self.save("a", result(self.track / "2026-10-12", [lap(14.0)])) / "report.md"
        set_report_link(rep, "/t/history.html", 2)
        set_report_link(rep, "/t/history.html", 3)
        text = rep.read_text()
        self.assertEqual(text.count("<!-- history -->"), 1)
        self.assertIn("(3 sessions): `/t/history.html`", text)

    def test_write_history_next_to_track(self):
        self.save("a", result(self.track / "2026-10-12", [lap(14.0), lap(15.0)], best=44.0))
        out = write_history(str(self.track), self.works, log=self.silent)
        self.assertEqual(out, self.track / "history.html")
        self.assertIn("<svg", out.read_text())
        data = json.loads((self.track / "history.json").read_text())
        self.assertEqual(data["sessions"][0]["best3"], 44.0)
        self.assertIn(str(out.resolve()), (self.works / "a" / "report.md").read_text())

    def test_no_sessions(self):
        with self.assertRaises(SystemExit):
            write_history(str(self.track), self.works, log=self.silent)


if __name__ == "__main__":
    unittest.main()
