# Track N

Copy this file to the track folder as `README.md`, one level above the batch folders:

```
TrackN/
  README.md          this file
  track.json         verified track profile (added later by `fpvlaps.py save-track`)
  track.npz
  1st/  2nd/ ...     one folder of DVR files per session
```

`fpvlaps.py analyze --videos TrackN/2nd` then finds this README on its own. The three bold lines below
are read by the tool (keep the labels as they are). Everything else is notes for people.

**Demo video:** https://www.youtube.com/watch?v=VIDEO_ID ("Organiser's demo video title")
**Flythrough starts at:** 1:00
**Correct lap:** `1st/hdz_0000` at 0:58.98

- **Demo video**: the organiser's flythrough. It's the real reference: a lap counts only if it flies
  the same gates in the same order and direction.
- **Flythrough starts at**: where the lap begins in the demo (`m:ss`).
- **Correct lap**: a start-gate crossing in your own footage that begins a full lap you have checked
  against the demo. The video path is relative to this folder (the extension may be left out). Give a
  time (`at 0:58.98`; it's turned into the nearest frame, so be as exact as you can) or a frame
  (`frame 3539`). It's only used while there's no `track.json` here.

The reference lap is picked in this order: `--track` / `--anchor` on the command line, `track.json`
next to this README, the correct lap, automatic calibration.

## Notes

Layout, common mistakes (e.g. skipped dives), lap time range.

## Results

| Batch | Best 3 consecutive | Video | Clip | YouTube |
|---|---|---|---|---|
