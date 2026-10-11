"""Race rules and tunables. Race rules are fixed by the skill; tunables can be overridden per track profile."""
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[2]
ASSETS = SKILL_DIR / "assets"

# ---- race rules (fixed) ----------------------------------------------------
LAPS_PER_RESULT = 3          # the result is always exactly 3 consecutive clean laps

# ---- feature extraction ----------------------------------------------------
THUMB_W, THUMB_H = 80, 60    # per-frame picture thumbnail (all later vision runs on these)
OCR_STEP = 3                 # OSD timer cells sampled every Nth frame
CALIB_SAMPLES = 48           # frames sampled to locate picture area + OSD timers
OSD_WHITE = 190              # grey level of OSD glyphs
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".ts", ".m4v")

# ---- motion / flight state -------------------------------------------------
STILL_MOTION = 1.2           # mean |frame diff| (80x60 grey) below this = parked / lying still
FLIGHT_MOTION = 4.0          # above this (smoothed) = flying
STALL_MOTION = 1.5           # 0.5 s window below this inside a lap = stopped / crashed
STALL_SECS = 0.5

# ---- lap detection ---------------------------------------------------------
DTW_STEP = 3                 # DTW runs at fps/3 (20 Hz for 60 fps footage)
DTW_CANDIDATE_COST = 0.62    # lap candidates (anything looser is not a lap)
CLEAN_COST_MIN, CLEAN_COST_MAX = 0.25, 0.38   # clamp for the auto clean-lap threshold
CLEAN_COST_PCTL, CLEAN_COST_FACTOR = 30, 1.55  # threshold = 30th percentile of lap costs x 1.55
GATE_FIT_MIN = 0.55                           # crossing must look like the consensus gate pass
FAST_OUTLIER = 0.82                           # laps faster than this x median clean lap = cut / missed gate
LAP_MIN_FACTOR, LAP_MAX_FACTOR = 0.6, 1.5     # valid lap duration relative to the track's lap period
PERIOD_RANGE_S = (5.0, 30.0)                  # plausible lap periods for whoop tracks
REFINE_WINDOW = list(range(-30, 31, 3))       # frames around a crossing used for 60 fps alignment
REFINE_SEARCH = 45                            # +- frames searched around a DTW boundary
