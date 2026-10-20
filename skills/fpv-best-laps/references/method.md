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
     correlation >= 0.6). Candidates are ranked by DTW cost across all videos, with a penalty for
     lap lengths far from the period.
   - *Shortcut check*: a short loop (e.g. one that skips a dive and flies straight back to the start
     gate) also starts and ends at the start gate and matches itself very well, so the best-ranked
     candidate can be wrong, and so can one whose ends aren't at the start gate. Each candidate is
     tried in turn (up to 6) and rejected if the laps it produces fail either check:
     - *length*: the typical clean lap is under 0.93x the lap period (it skips part of the course);
     - *chaining*: under 70% of back-to-back laps share their crossing. With a reference that starts
       and ends at the start gate, consecutive laps chain; otherwise each lap ends seconds before the
       next starts. Measured: 86-88% on correct references, 32-37% on wrong ones. If none passes, the best one is kept and `report.md` carries a
     **"reference lap looks wrong"** warning. With `--anchor` or `--track` the same check only warns.
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
   - its duration is outside 0.82-1.5x the lap period. The period is measured from the session's own
     footage, also with `--track`, so a pilot who got faster since the profile was made isn't
     penalised. A loop that skips part of the course comes out well under 0.82x.
   - the quad stopped (motion below 1.5 for 0.5 s).
   - either boundary fits the consensus gate pass poorly (fit < 0.55): a missed or re-flown gate.
   - it is faster than 0.82x the typical clean lap (a missed gate or cut course).
   A winning window with a lap more than 10% faster than typical gets a **warning** in `report.md`,
   which means check the crossings sheet before trusting it.
6. **Best window**: every run of 3 clean laps that share crossings, ranked by total.
6b. **Sector splits** (`sectors.py`): the reference lap is split into sectors, evenly (3 by default,
   `--sectors N`) or at reference-video frames (`--sectors F1,F2,...`, saved as `sectors` in
   `track.json`, so later batches use the same splits). Each clean lap is aligned to the reference lap
   with a fixed-endpoint DTW at 20 Hz (steps (1,1), (1,2), (2,1)), and each boundary is carried along
   the alignment path into the lap. It is then snapped to the exact frame (±9 frames) against the
   consensus view of that boundary: the mean ±0.5 s window over the mapped boundaries of the ~40
   best-matching clean laps, as for gate crossings. A lap whose boundaries come out of order gets no
   sectors. The **theoretical best** is the sum of the best time in each sector over all clean laps.
   Measured on Track 2 batch 2nd: 48 of 48 clean laps timed, theoretical best 12.83 s vs best lap
   13.50 s; the mapped boundaries showed the same view in every lap checked. Mid-lap points are less
   distinctive than the start gate, so a sector time is good to about ±3-5 frames, not ±2.
7. **Render** (`render.py`): ffmpeg cuts the clip frame-accurately and, in the same pass, fills
   black side bars with a blurred, dimmed copy of the picture (`active_area`, `blur_filter`;
   `--background black` turns it off). With `--music`, a last ffmpeg pass mixes a track (a file, or one
   generated by `music.py`) 10 dB under the levelled motor audio. The overlay is either the
   HyperFrames composition `assets/overlay/index.html` (GSAP timeline, running lap clock, pinned
   `hyperframes@0.8.145`) or the OpenCV fallback with the same layout.
7b. **Lap comparison** (`compare.py`, `compare`): two laps, from one session or two sessions of the
   track, each read from its own work directory (lap frames from `result.json`, thumbnails from
   `features/`). The 20 Hz descriptors of lap B are aligned to those of lap A with the same
   fixed-endpoint DTW as the sector splits. That gives, for every point of lap A, the frame of lap B at
   the same point of the course. The **running gap** is A's frame minus B's frame at each point,
   smoothed over 0.5 s, pinned to 0 at the start gate and to the lap-time difference at the finish, so
   it is known everywhere in the lap, not only at the finish. Sector boundaries come from both laps'
   own sector splits when they share a reference lap (deltas then match `report.md` exactly), else from
   lap A's splits (or lap B's mapped across), else an even split of lap A. Lap B's point at each
   boundary is snapped at 60 fps (±15 frames, best match of lap A's ±0.5 s view there), and the gap
   curve is bent through those points. Default pair: the best clean lap of `--work` against the best
   clean lap of every session `history` collects for the track. Measured on Track 2 batch 2nd (laps
   with sector splits from the same session): sector times read through the pairwise alignment agree
   with each lap's own splits to 0.05 s on average. The video is 1920x1080: both laps cropped to the
   picture, side by side, both lap clocks and a gap chart with a cursor at lap A's position. Each lap's
   footage runs on past its finish until the slower lap ends. OpenCV renders it by default (41 s for
   the 15.8 s Track 2 clip); HyperFrames (`assets/compare/index.html`, `--renderer hyperframes`) gives
   the same layout with nicer type but took 14.8 min (screenshot capture on software GL). One lap's
   audio or none.

## Verifying a run (`verify`, optional)

8. **Source** (`youtube.py`, only with `--url`): `yt-dlp` picks the highest frame rate, then the
   highest resolution, preferring H.264 (OpenCV seeks it frame-accurately). A variable-frame-rate
   download, or a `--start`/`--end` section, is re-encoded at a constant frame rate with ffmpeg's
   `fps` filter (frames placed on their real timestamps); the section start is kept as an offset so
   every crossing links back to the right second of the video. The result is a one-video batch in
   `<work>/source/youtube/`, timed by steps 1-6 unchanged. Below 50 fps the rate is doubled with
   blended in-between frames (`framerate` filter): lap matching steps in frames, so a 30 fps video
   against a 60 fps profile would look like a lap flown at 2x speed, and plain duplicate frames would
   zero the motion of every other frame.
9. **Edits** (`verify.py`): an `mm:ss` timer that runs advances exactly as fast as the footage. Each
   reading `s` at video time `t` bounds the offset `c` in `floor(t + c) = s` to `[s - t, s - t + 1)`;
   intersecting these over a run pins `c` to a frame or two (0.15 s allowed for OSD refresh jitter).
   Runs shorter than 1.5 s or without a tick are dropped (OCR glitches, a frozen timer while
   disarmed). Between runs, a reset to ~0 is a re-arm, a backwards shift after a gap is a disarm pause,
   and a forward shift (or a sudden backwards one) is an **edit**. A timer slot can show a different
   timer for a while (Betaflight's crash-flip mode swaps the on-time timer into the fly-timer slot), so
   an edit only counts when every other readable timer shows the same shift. Tested on 23 raw HDZero
   recordings: no false edits. Edits below ~0.3 s are not seen.
10. **Claim**: every chain of 3 consecutive laps that share crossings, clean or not, is compared with
    the claimed **total**, within ±3 frames (at least 0.05 s). Claimed lap times are only shown, against
    ±0.15 s: pilots time from their own line, and on Whooperza's Track 2 upload the pilot's lap timer
    ticked 4-10 frames after the tool's crossings, which moved -0.08/+0.11/-0.05 s between the laps
    while the total differed by 0.03 s. The verdict is **verified** for a clean chain without edits within tolerance,
    **mismatch** otherwise (the closest clean chain, or the matching chain with why it doesn't count),
    **not verifiable** with no chain or with a "reference lap looks wrong" warning.

**Single-video calibration is the weak spot.** An upload is one video, often a clip that starts
mid-flight. Automatic calibration then has one parked start or none and few laps to learn the start
gate from, and the laps being checked are the ones that define the reference. Tested on two other
pilots' uploads: neither had a parked start the calibration accepts (one starts mid-flight, one sits
still for 2.5 s), so both needed `--anchor`, found from the clip's own lap-timer overlay or from the
gate pass in the opening seconds. A track profile only fits the **same build** of the track: each
pilot builds the layout at home, and another pilot's room matched the user's Track 2 profile at the
same cost as the user's own upload (and scored higher on raw frame similarity), so a wrong-room
profile can't be detected and still yields "laps". Use a profile only for the pilot who made it.
`verify.md` marks a verdict from self-calibration as less certain.

## Tunables (`scripts/fpvlaps/config.py`)

| Constant | Default | Change when |
|---|---|---|
| `PERIOD_RANGE_S` | 5-30 s | Very short or very long tracks |
| `STILL_MOTION` / `FLIGHT_MOTION` | 1.2 / 4.0 | Very noisy analog footage (raise both) |
| `CLEAN_COST_MIN/MAX`, `CLEAN_COST_FACTOR` | 0.25 / 0.38, 1.55 | Clean laps rejected as off-line (raise), or crash laps passing (lower) |
| `FAST_OUTLIER` | 0.82 | Pilots with very uneven lap times |
| `GATE_FIT_MIN` | 0.55 | Valid laps rejected for "doesn't look like a gate pass" (lower it) |
| `LAP_MIN/MAX_FACTOR` | 0.82 / 1.5 | Wildly varying lap times |
| `SHORT_LOOP_RATIO` | 0.93 | Shortcut-loop warning on a correct reference (lower), or a shortcut reference not caught (raise) |
| `CHAIN_MIN` | 0.7 | Chaining warning on a correct reference (lower) |
| `MAX_REFERENCE_TRIES` | 6 | More reference candidates to try before warning |
| `OSD_WHITE` | 190 | OSD glyphs darker or greyer than usual |
| `SECTORS_DEFAULT` | 3 | More or fewer sectors by default (`--sectors N` per run) |
| `SECTOR_REFINE_SEARCH` | 9 | How far (frames) a mapped sector boundary may move when snapped to the consensus view |
| `compare.SMOOTH_S` / `SNAP_SEARCH` | 0.5 s / 15 | Running gap smoothing; how far lap B's point at a sector boundary may move when snapped |

`LAPS_PER_RESULT = 3` is a race rule, not a tunable.

## Known limits

- The timing line is the start spot in front of the gate, matched visually. Accuracy is about ±2-3
  frames per crossing. Individual lap splits shift slightly if `--anchor` moves the line (the 3-lap
  total barely changes).
- Calibrating from very few videos (2-3) is less reliable: verify the sheets, or reuse a profile
  made from a bigger session with `--track`.
- A lap where the pilot loops back through the gate area is ambiguous. The warning above catches
  the usual symptom (an unusually fast lap).
- Laps that cut the course but still look like the reference lap are not detected as invalid,
  unless they are much shorter than the lap period. The tool only compares laps with each other:
  the official track layout (e.g. the organiser's demo flythrough) is the real reference, so check
  the winning laps against it.
- A crash at the very end of a lap (the drone tumbles through the start-gate area and flies on) is
  not detected from motion or crossing similarity; tested on real footage, neither separates it
  from a clean finish. In practice such "laps" are shortcut loops and fail the length checks above.
- Videos that never start parked are still timed (the reference comes from the others), but if no
  video starts parked, `--anchor` is required.
- The lap matcher ignores fixed edge bands of the picture where OSD elements usually sit (`laps.KEEP`).
  OSD elements in the middle of the picture are not masked; static ones are harmless, but a ticking
  element there adds a little noise to the match cost.
- OSD digit templates come from Betaflight's default font. Other fonts fall back to motion-based arm
  detection.
- **Wide OSD layout.** Two other pilots' HDZero uploads (RaceGOW Track 2) draw the same glyphs on a
  40 px character pitch instead of 32 px (`osd.WIDE_PITCHES` tries 34-44). These timers are stored as
  `(cx, cy, dy, pitch)` and only searched for when the default layout finds **no** timer, so footage
  with default timers extracts exactly as before (checked on all 58 readable Track 1/Track 2
  recordings, including 2 with no default timer). A wide candidate must also trend upward like a clock over the calibration samples (Spearman rank
  correlation >= 0.7 with video order), because a link-quality readout such as `LQ 28:100` also
  reads as mm:ss. On those uploads about 1 digit in 4 is misread (mostly `0` as `3`), which breaks
  `osd.arm_segments` (it tolerates only isolated glitches). So arm detection ignores wide timers and
  stays on motion. `verify` uses them, because its clock fit (step 9) drops glitches: to find edits,
  and to overrule a motion-guessed "disarmed during lap" when the timer runs unbroken through the
  lap (clips cut tight around the run put the first and last crossing at the edge of the motion
  segment).
