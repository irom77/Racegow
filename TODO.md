# TODO

## Remove hard-coded local paths

These files contain absolute paths from the original development machine (including a Windows
username). They work only there and expose local directory names in a public repo.

- [ ] `src/extract.py`: `SRC` (Windows video folder under `/mnt/c/Users/...`) and `OUT`
  (`/home/irom/RaceGow6/work/feat`). Replace with command-line arguments or environment variables.
- [ ] `src/analyze.py`: `FEAT`, `CENT` (`work/cent_all.npy`) and the `analysis.json` output path.
  Same fix. Note `cent_all.npy` is not committed; point to `skills/fpv-best-laps/assets/osd_digits.npz`
  instead, or mark `src/` as an archived prototype.
- [ ] Check the remaining `src/` modules (`gatematch.py`, `redtrack.py`, `lapdtw.py`, `osd.py`) for
  the same pattern: `grep -rn "/mnt/c\|/home/" src/`.
- [ ] `skills/fpv-best-laps/evals/evals.json`: the test prompt names a personal video folder.
  Replace with a placeholder such as `/path/to/videos`.
- [ ] Optional: rewrite git history (`git filter-repo`) if the old paths should disappear from
  earlier commits too, not just the latest one.
