"""Unit tests for the YouTube input and run verification (no network, no video decoding)."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fpvlaps.verify import parse_claim, tolerance, timer_jumps, confirmed_cuts, chains, judge  # noqa: E402
from fpvlaps.youtube import video_id, link, is_vfr  # noqa: E402

FPS, STEP = 60.0, 3


def timer(*pieces):
    """OSD readings every STEP frames: pieces of (seconds of video, timer value at the piece start,
    timer running?)."""
    out = []
    for dur, t0, running in pieces:
        n = int(dur * FPS / STEP)
        out += [np.floor(t0 + (k * STEP / FPS if running else 0)) for k in range(n)]
    return np.array(out, float)


OFFLINE = "off-line/crash: lap doesn't match the reference lap"


def lap(video, start, end, clean=True, reason="", cost=0.25, fit=(0.8, 0.8)):
    return dict(video=video, start=start, end=end, time=round((end - start) / FPS, 3), clean=clean, reason=reason,
                cost=cost, fit=list(fit))


def chain(*times, video="v", start=600, clean=None, costs=None, reason=OFFLINE):
    laps, f = [], start
    for i, t in enumerate(times):
        e = f + int(round(t * FPS))
        ok = True if clean is None else clean[i]
        laps.append(lap(video, f, e, ok, "" if ok else reason, costs[i] if costs else 0.25))
        f = e
    return laps


class TestClaim(unittest.TestCase):
    def test_total_and_splits(self):
        self.assertEqual(parse_claim("30.82"), dict(total=30.82, laps=None))
        self.assertEqual(parse_claim("10.27,10.33,10.22"), dict(total=30.82, laps=[10.27, 10.33, 10.22]))
        self.assertEqual(parse_claim("10.27 + 10.33 + 10.22s")["laps"], [10.27, 10.33, 10.22])
        self.assertIsNone(parse_claim(None))

    def test_bad_claims(self):
        for s in ("10.2,10.3", "fast", "1,2,3,4"):
            with self.assertRaises(SystemExit):
                parse_claim(s)

    def test_tolerance_scales_with_frame_rate(self):
        self.assertAlmostEqual(tolerance(60), 0.05)
        self.assertAlmostEqual(tolerance(30), 0.10)
        self.assertAlmostEqual(tolerance(120), 0.05)
        self.assertEqual(tolerance(60, 0.2), 0.2)


class TestYoutube(unittest.TestCase):
    def test_video_id(self):
        for u in ("https://youtu.be/GG7-ezzppak", "https://www.youtube.com/watch?v=GG7-ezzppak&t=60s",
                  "youtube.com/shorts/GG7-ezzppak", "https://m.youtube.com/embed/GG7-ezzppak", "GG7-ezzppak",
                  "https://youtu.be/GG7-ezzppak?si=abc"):
            self.assertEqual(video_id(u), "GG7-ezzppak", u)
        for u in ("https://vimeo.com/123", "https://www.youtube.com/channel/UCxyz", "nope"):
            with self.assertRaises(SystemExit):
                video_id(u)

    def test_link_lands_just_before(self):
        self.assertEqual(link("GG7-ezzppak", 61.9), "https://youtu.be/GG7-ezzppak?t=60")
        self.assertEqual(link("GG7-ezzppak", 0.4), "https://youtu.be/GG7-ezzppak?t=0")

    def test_vfr(self):
        self.assertFalse(is_vfr((60.0, 60.0)))
        self.assertTrue(is_vfr((60.0, 57.3)))
        self.assertFalse(is_vfr(None))


class TestTimerJumps(unittest.TestCase):
    def test_continuous_timer_has_no_jumps(self):
        self.assertEqual(timer_jumps(timer((40, 3.4, True)), FPS, STEP), [])

    def test_ocr_glitches_ignored(self):
        s = timer((40, 3.4, True))
        s[[50, 51, 300]] = [77, np.nan, 1]
        self.assertEqual(timer_jumps(s, FPS, STEP), [])

    def test_cut_forward(self):
        # 20 s, then 5 s of footage removed: the timer is 5 s further on than the video
        j = timer_jumps(timer((20, 3.4, True), (20, 28.4, True)), FPS, STEP)
        self.assertEqual([x["kind"] for x in j], ["cut"])
        self.assertAlmostEqual(j[0]["shift"], 5.0, delta=0.1)
        self.assertAlmostEqual(j[0]["frame"], 20 * FPS, delta=STEP)

    def test_short_cut_found(self):
        j = timer_jumps(timer((20, 3.4, True), (20, 23.9, True)), FPS, STEP)
        self.assertEqual([x["kind"] for x in j], ["cut"])

    def test_cut_back(self):
        j = timer_jumps(timer((20, 3.4, True), (20, 15.0, True)), FPS, STEP)
        self.assertEqual([x["kind"] for x in j], ["cut"])

    def test_rearm_and_pause_are_not_cuts(self):
        j = timer_jumps(timer((20, 3.4, True), (4, 23.4, False), (20, 0.0, True)), FPS, STEP)
        self.assertEqual([x["kind"] for x in j], ["re-arm"])
        j = timer_jumps(timer((20, 3.4, True), (4, 23.4, False), (20, 23.4, True)), FPS, STEP)
        self.assertEqual([x["kind"] for x in j], ["pause"])

    def test_frequent_misreads_still_one_run_and_cut_found(self):
        # 1 reading in 4 misread (as on other pilots' uploads): the clock must still fit, and a cut show
        rng = np.random.default_rng(1)
        s = timer((20, 3.4, True), (20, 28.4, True))
        bad = rng.random(len(s)) < 0.25
        s[bad] = s[bad] + rng.choice([30, -30, 1800, 4], bad.sum())
        j = timer_jumps(s, FPS, STEP)
        self.assertEqual([x["kind"] for x in j], ["cut"])
        self.assertAlmostEqual(j[0]["shift"], 5.0, delta=0.2)

    def test_cut_must_move_every_timer(self):
        fly = timer((20, 3.4, True), (20, 23.4, True))
        on = timer((40, 30.2, True))
        swapped = fly.copy()
        swapped[200:300] = on[200:300]              # crash-flip mode shows the on-time timer in the fly slot
        both = np.stack([swapped, on], 1)
        self.assertEqual([j for j in confirmed_cuts(both, [0, 1], FPS, STEP) if j["kind"] == "cut"], [])
        cut = np.stack([timer((20, 3.4, True), (20, 28.4, True)), timer((20, 30.2, True), (20, 55.2, True))], 1)
        self.assertEqual([j["kind"] for j in confirmed_cuts(cut, [0, 1], FPS, STEP)], ["cut"])


class TestJudge(unittest.TestCase):
    R = dict(warnings=[], clean_cost_threshold=0.38)

    def judge(self, laps, claim, cuts=None, **R):
        return judge(dict(self.R, laps=laps, **R), parse_claim(claim), 0.05, {"v": cuts or []})

    def test_chains_need_shared_crossings(self):
        laps = chain(10, 10, 10) + [lap("v", 99999, 100600)]
        self.assertEqual(len(chains(laps)), 1)

    def test_verified_total_and_splits(self):
        laps = chain(12, 10.27, 10.33, 10.22, 11)
        v, _, w, _ = self.judge(laps, "30.82")
        self.assertEqual(v, "verified")
        self.assertEqual([l["time"] for l in w["laps"]], [10.267, 10.333, 10.217])
        self.assertEqual(self.judge(laps, "10.27,10.33,10.22")[0], "verified")

    def test_total_decides_splits_are_information(self):
        # Whooperza, Track 2: the pilot's timing line sits 4-10 frames after the tool's
        laps = chain(14.55, 14.917, 13.70)
        v, why, w, _ = self.judge(laps, "14.63,14.81,13.75")
        self.assertEqual(v, "verified")
        self.assertIn("every claimed lap time within", why)

    def test_splits_far_off_are_flagged_not_failed(self):
        v, why, _, _ = self.judge(chain(10.27, 10.33, 10.22), "10.67,10.03,10.12")
        self.assertEqual(v, "verified")
        self.assertIn("lap 1 is -0.40s off", why)

    def test_total_outside_tolerance_is_mismatch_even_with_close_splits(self):
        self.assertEqual(self.judge(chain(10.27, 10.33, 10.22), "10.30,10.36,10.25")[0], "mismatch")

    def test_mismatch_reports_closest_clean_chain(self):
        v, why, w, _ = self.judge(chain(10.5, 10.5, 10.5, 10.6), "30.82")
        self.assertEqual(v, "mismatch")
        self.assertEqual(w["total"], 31.5)
        self.assertIn("closest clean chain", why)

    def test_claim_on_rejected_lap_is_mismatch(self):
        v, why, w, _ = self.judge(chain(10.27, 10.33, 10.22, clean=[True, False, True]), "30.82")
        self.assertEqual(v, "mismatch")
        self.assertIn("lap 2 rejected", why)

    def test_upload_with_raised_cost_everywhere_still_verifies(self):
        # re-encoding + a burned-in overlay: every lap costs ~0.5, nothing stands out
        laps = chain(13.87, 13.85, 13.72, clean=[False] * 3, costs=[0.47, 0.50, 0.51])
        v, why, w, _ = self.judge(laps, "13.85,13.85,13.73")
        self.assertEqual(v, "verified")
        self.assertEqual(len(w["caveats"]), 3)
        self.assertIn("crossing sheet", why)

    def test_lap_standing_out_from_its_upload_stays_rejected(self):
        laps = chain(13.87, 13.85, 13.72, 14, 14, clean=[False] * 5, costs=[0.47, 0.75, 0.48, 0.46, 0.47])
        v, why, _, _ = self.judge(laps, "13.85,13.85,13.73")
        self.assertEqual(v, "mismatch")
        self.assertIn("lap 2 rejected", why)

    def test_other_rejections_are_never_softened(self):
        laps = chain(13.87, 13.85, 13.72, clean=[False] * 3, costs=[0.47, 0.50, 0.51],
                     reason=OFFLINE + "; quad stopped inside the lap (crash)")
        self.assertEqual(self.judge(laps, "13.85,13.85,13.73")[0], "mismatch")

    def test_motion_disarm_overruled_by_unbroken_timer(self):
        # RealSco: armed state from motion (no default-layout timer); the clip is cut tight around the
        # run, so motion puts the first and last crossings outside the "armed" segment
        dis = "disarmed during lap (OSD timer stopped/reset)"
        laps = chain(11.33, 11.0, 11.25, clean=[False, True, False], reason=dis)
        timer = dict(jumps=[], spans=[(0, 2700)])
        v, why, w, _ = judge(dict(self.R, laps=laps), parse_claim("33.58"), 0.05, {"v": []}, {"v": timer})
        self.assertEqual(v, "verified")
        self.assertEqual(len(w["caveats"]), 2)
        # a timer that re-arms inside lap 1 keeps the rejection
        timer = dict(jumps=[dict(frame=900, kind="re-arm", shift=-5.0)], spans=[(0, 880), (900, 2700)])
        self.assertEqual(judge(dict(self.R, laps=laps), parse_claim("33.58"), 0.05, {"v": []}, {"v": timer})[0],
                         "mismatch")
        # unreadable near the lap end: no evidence, rejection stays
        timer = dict(jumps=[], spans=[(0, 1200)])
        self.assertEqual(judge(dict(self.R, laps=laps), parse_claim("33.58"), 0.05, {"v": []}, {"v": timer})[0],
                         "mismatch")

    def test_lap_spanning_a_cut_does_not_count(self):
        laps = chain(10.27, 10.33, 10.22)
        v, why, _, _ = self.judge(laps, "30.82", cuts=[dict(frame=laps[1]["start"] + 100, shift=4.0)])
        self.assertEqual(v, "mismatch")
        self.assertIn("lap 2 spans an edit", why)

    def test_wrong_reference_is_not_verifiable(self):
        self.assertEqual(self.judge(chain(10.27, 10.33, 10.22), "30.82", warnings=["looks wrong"])[0],
                         "not verifiable")

    def test_no_laps_not_verifiable(self):
        self.assertEqual(self.judge(chain(10, 10), "20")[0], "not verifiable")

    def test_no_claim_reports_best(self):
        v, _, w, _ = self.judge(chain(11, 10, 10, 10, 12), None)
        self.assertEqual((v, w["total"]), ("detected", 30.0))


if __name__ == "__main__":
    unittest.main()
