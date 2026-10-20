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
LAP_MIN_FACTOR, LAP_MAX_FACTOR = 0.82, 1.5    # valid lap duration relative to this session's lap period
                                              # (a lap that skips part of the course comes out much shorter)
SHORT_LOOP_RATIO = 0.93                       # typical clean lap below this x lap period = the reference lap
                                              # is a shortcut loop (e.g. a skipped dive); try another one
CHAIN_MIN = 0.7                               # share of back-to-back laps that share their crossing; a
                                              # reference that doesn't start/end at the gate leaves gaps
MAX_REFERENCE_TRIES = 6                       # auto calibration: reference candidates tried before giving up
PERIOD_RANGE_S = (5.0, 30.0)                  # plausible lap periods for whoop tracks
REFINE_WINDOW = list(range(-30, 31, 3))       # frames around a crossing used for 60 fps alignment
REFINE_SEARCH = 45                            # +- frames searched around a DTW boundary

# ---- sector splits ---------------------------------------------------------
SECTORS_DEFAULT = 3                           # reference lap split evenly into this many sectors
SECTOR_REFINE_SEARCH = 9                      # +- frames a DTW-mapped sector boundary may move when
                                              # snapped to the consensus view of that point
