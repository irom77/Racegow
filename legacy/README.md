# Legacy prototype (not maintained)

This is the original single-track prototype the tool grew out of. It is kept for reference only and
is not meant to be run: the input/output folders at the top of `extract.py` and `analyze.py` are
placeholders, and `analyze.py` needs a gate-centroid file (`work/cent_all.npy`) that was never committed.

**Use [`skills/fpv-best-laps/`](../skills/fpv-best-laps/) instead.** It replaces everything here,
takes your video folder as an argument, and ships the only model file it needs
(`assets/osd_digits.npz`, the OSD digit templates). Quick start is in the [main README](../README.md#quick-start).
