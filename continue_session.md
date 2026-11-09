# eyeLens — Continue Session

**Memory:** `plans/handoffs/HANDOFF_eyelens-calibration-v2_2026-11-09.md`
**Status:** v0.2.0 implemented, tested and pushed. Nothing running. A real-face
calibration is the first pending step.
**Repo:** `https://github.com/Closegamer/eyeLens` (private, branch `main`)
**Code commit:** `7de4db4` · tag `v0.2.0`
**Chain:** `standalone-08a28c4a` seq 2

## What changed in v0.2.0

- **Zoom is now true zoom-in.** The lens samples `diameter / zoom` and draws it
  into the lens. Previously it sampled `diameter * zoom`, i.e. zoomed out.
- **Lens follow is slower by default.** Default smoothing is 0.72, the 1€
  filter is calmer, and the overlay uses an 85 ms centre easing. The slider
  still allows a faster lens.
- **Calibration is rebuilt.** Roll-corrected eye features, fixed `head_roll`,
  `face_size` distance proxy, 52-term ridge + kernel-ridge residual model,
  grouped leave-one-point-out CV, and a separate 9-point accuracy check.
- Calibration now takes ~50 s (25 training dots + 9 green check dots). The
  result screen shows the held-out error in pixels.
- Old calibrations are invalid (feature/model version bump). Old settings are
  migrated once to the calmer smoothing default.

## What is next

1. Run `run.bat`, complete the 25 + 9 calibration with a real face, and note the
   reported accuracy from the result screen.
2. If the error is still high or the lens drifts, inspect
   `%LOCALAPPDATA%\eyeLens\calibration.json` (`validation_rmse`, `loo_rmse`,
   `krr_weight`, `worst_point_rmse`) and read the full handoff.
3. The most likely next accuracy improvement is adding MediaPipe
   facial-transformation-matrix (head pose) features if real testing still
   shows drift when the head moves.

## Exact state

- Virtualenv: `C:\a_REPOS\eyeLense\.venv` (Python 3.12).
- Version: `0.2.0`.
- Tests: 23 passed; ruff clean; smoke test exit 0.
- `Modelfile` in the repo root is still an unrelated pre-existing file; leave it
  untracked.
- This memory file and the v0.2 handoff are committed in the session commit
  after `7de4db4`.
