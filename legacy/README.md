# Legacy prototype (not maintained)

This is the original single-track prototype the tool grew out of. It is kept for reference only and
does not run outside the machine it was written on: input/output folders and a gate-centroid file
(`work/cent_all.npy`, never committed) are hard-coded at the top of `extract.py` and `analyze.py`.

**Use [`skills/fpv-best-laps/`](../skills/fpv-best-laps/) instead.** It replaces everything here,
takes your video folder as an argument, and ships the only model file it needs
(`assets/osd_digits.npz`, the OSD digit templates). Quick start is in the [main README](../README.md#quick-start).
