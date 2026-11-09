# eyeLens — Continue Session

**Memory:** `plans/handoffs/HANDOFF_eyelens-eye-only-model_2026-11-09.md`
**Status:** v0.6.0 implemented, tested and pushed. Nothing running. Restart and
re-test; a fresh real-face calibration is the next acceptance test.
**Repo:** `https://github.com/Closegamer/eyeLens` (private, branch `main`)
**Code commit:** `fcc4b60` · follow-up `1cfe01f` · tag `v0.6.0`
**Chain:** `standalone-08a28c4a` seq 6

## What changed in v0.6.0

- **The gaze model now fits only the 8 eye-in-head features** (iris positions,
  iris average, vergence). Real calibration data showed the old all-14 model
  had held-out error **234 px**; eye-only is **~104 px (LOO 93)**.
- Raw head/face features were learning slow head drift as a gaze cue. They are
  still saved for diagnostics and for the head-still warning, but are masked
  from the fitted model.
- **Existing calibration files are refitted with the eye-only model on load.**
  Their stale validation number and old drag corrections are dropped. On this
  machine the old calibration now shows **“Good · ±93 px”** (estimated) instead
  of 234 px.
- **Calibration order is now centre-first plus a fixed shuffle**, so slow head
  drift is spread across the screen.
- **Head-drift warning**: the first point sets a head baseline; if the user
  drifts, the header/bottom hint says “Head moved — return to your starting head
  position” and sampling pauses for that point.
- Version `0.6.0`.

## What is next

1. Restart eyeLens. The existing calibration refits eye-only and should be
   noticeably better without recalibrating.
2. If still off, recalibrate to get the shuffled order and head-drift warning.
   Re-do mouse corrections afterward; the old ones were discarded.
3. If accuracy is still not enough, next options:
   - denser 6×6/7×7 calibration grid;
   - MediaPipe head-pose (facial transformation matrix) features;
   - crop-based landmark inference on the eye region.
4. Real-face calibration and mouse-correction quality remain the pending tests.

## Exact state

- Virtualenv: `C:\a_REPOS\eyeLense\.venv` (Python 3.12).
- Version: `0.6.0`.
- Tests: 31 passed; ruff clean; smoke test exit 0; synthetic calibration E2E
  passes; old real calibration loads with LOO 93 and 0 corrections.
- `Modelfile` in the repo root is still an unrelated pre-existing file; leave it
  untracked.
- This memory file and the v0.6 handoff are committed in the session commit
  after `fcc4b60`.
