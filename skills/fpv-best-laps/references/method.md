# How fpv-best-laps works

Read this when results look wrong or footage differs from the usual "HDZero recording of a whoop
track that starts parked at the gate".

## Pipeline

1. **Extract** (`extract.py`, one sequential decode per video, cached)
   - *Picture box*: non-black area of sampled frames (removes 4:3 pillarbox bars).
   - *OSD timers*: anywhere in the frame, persistent white glyphs are searched for a `:` (two
     stacked dots). The dot spacing gives the glyph scale, so any resolution or OSD position works.
     A candidate counts as a timer only if it reads as a valid `mm:ss` in at least 30% of the samples
     and shows at least 3 different values (static text such as a `3.50v` battery reading is
     rejected). Up to 3 timers are kept; each one's 4 digit cells are stored every 3rd frame.
   - Per frame: an 80x60 thumbnail of the picture, plus motion (mean absolute frame difference).
2. **Arm state** (`osd.py`, `analyze.arm_info`): a timer that counts only while armed ticks 1 s per
   second during flight. "Timer minus video time" is constant while flying, changes while disarmed,
   and jumps on re-arm. Runs of constant offset are the armed segments. **One timer is enough**: a
   per-arm timer (resets on arm) or a total-armed timer (pauses when disarmed) both work. A per-arm
   timer is slightly better, because it also reveals a quick disarm-rearm after a crash. With several
   timers, the one that yields the most armed segments wins (ties: the smaller reading). A power-on
   timer never pauses, so it never wins over an armed timer; if it is the only one, disarms go
   undetected and the stall and off-line checks carry the crash filtering. OCR uses the bundled
   Betaflight/HDZero digit templates (`assets/osd_digits.npz`). Without a readable timer, flight
   segments come from motion.
3. **Track calibration** (`track.py`), with no layout knowledge:
   - *Race start*: recordings open with a few seconds of handling, then the quad sits on the start
     spot facing the start gate (props idling or hovering in place), then launches. The parked view is
     the longest stretch of near-identical frames in the first 90 s. **Launch** is when the view
     leaves it for good. On the reference footage the gate is crossed 0.5-1 s after launch.
   - *Lap period*: peak of descriptor self-similarity (Gram-matrix diagonals) over lags of 5-30 s.
   - *Candidate laps*: in-flight frames resembling the parked view, paired about one period apart in
     one armed segment. A candidate is kept only if its two ends look like the same place (window
     correlation >= 0.6). The winner has the lowest DTW cost across all videos, with a penalty for
     lap lengths far from the period.
   - *Start line*: a takeoff flies the opening of a lap, only slower. Each takeoff's first 3 s
     (compressed 1-3x) is DTW-aligned into the candidate lap cycle. Where launch lands is the start
     line, and the reference lap is re-cut to begin and end there. The timing line therefore sits on
     the start spot directly in front of the start gate, about 0.4 s before the quad passes under
     the gate's top bar.
   - Saved to `track.json`/`track.npz`. `--anchor VIDEO:FRAME` replaces this step with a known crossing.
4. **Laps** (`laps.py`): subsequence DTW (speed 0.5x-2x) of the reference lap inside every video
   finds lap candidates. Adjacent laps may overlap by 0.6 s at their shared boundary. Each boundary
   is then refined at full frame rate, in two passes: first against the reference lap's two
   crossings, then against a **consensus template** (the mean ±0.5 s window of the ~40 best-matching
   crossings in all videos). Every crossing is therefore measured at the same point of the track
   (±1-2 frames on the reference footage).
5. **Clean filter**: a lap is rejected if
   - its DTW cost is above the 30th-percentile lap cost × 1.55 (clamped 0.25-0.38), meaning the
     picture left the racing line (crash, detour, tumble).
   - its start and end are not in one armed segment (disarm).
   - its duration is outside 0.6-1.5x the lap period.
   - the quad stopped (motion below 1.5 for 0.5 s).
   - either boundary fits the consensus gate pass poorly (fit < 0.55): a missed or re-flown gate.
   - it is faster than 0.82x the typical clean lap (a missed gate or cut course).
   A winning window with a lap more than 10% faster than typical gets a **warning** in `report.md`,
   which means check the crossings sheet before trusting it.
6. **Best window**: every run of 3 clean laps that share crossings, ranked by total.
7. **Render** (`render.py`): ffmpeg cuts the clip frame-accurately. The overlay is either the
   HyperFrames composition `assets/overlay/index.html` (GSAP timeline, running lap clock, pinned
   `hyperframes@0.8.145`) or the OpenCV fallback with the same layout.

## Tunables (`scripts/fpvlaps/config.py`)

| Constant | Default | Change when |
|---|---|---|
| `PERIOD_RANGE_S` | 5-30 s | Very short or very long tracks |
| `STILL_MOTION` / `FLIGHT_MOTION` | 1.2 / 4.0 | Very noisy analog footage (raise both) |
| `CLEAN_COST_MIN/MAX`, `CLEAN_COST_FACTOR` | 0.25 / 0.38, 1.55 | Clean laps rejected as off-line (raise), or crash laps passing (lower) |
| `FAST_OUTLIER` | 0.82 | Pilots with very uneven lap times |
| `GATE_FIT_MIN` | 0.55 | Valid laps rejected for "doesn't look like a gate pass" (lower it) |
| `LAP_MIN/MAX_FACTOR` | 0.6 / 1.5 | Wildly varying lap times |
| `OSD_WHITE` | 190 | OSD glyphs darker or greyer than usual |

`LAPS_PER_RESULT = 3` is a race rule, not a tunable.

## Known limits

- The timing line is the start spot in front of the gate, matched visually. Accuracy is about ±2-3
  frames per crossing. Individual lap splits shift slightly if `--anchor` moves the line (the 3-lap
  total barely changes).
- Calibrating from very few videos (2-3) is less reliable: verify the sheets, or reuse a profile
  made from a bigger session with `--track`.
- A lap where the pilot loops back through the gate area is ambiguous. The warning above catches
  the usual symptom (an unusually fast lap).
- Laps that cut the course but still look like the reference lap are not detected as invalid.
- Videos that never start parked are still timed (the reference comes from the others), but if no
  video starts parked, `--anchor` is required.
- The lap matcher ignores fixed edge bands of the picture where OSD elements usually sit (`laps.KEEP`).
  OSD elements in the middle of the picture are not masked; static ones are harmless, but a ticking
  element there adds a little noise to the match cost.
- OSD digit templates come from Betaflight's default font. Other fonts fall back to motion-based arm
  detection.
