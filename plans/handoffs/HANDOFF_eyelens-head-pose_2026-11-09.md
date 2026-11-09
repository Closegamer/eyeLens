# eyeLens — head-pose correction layer (v0.7.0)

**Date:** 2026-11-09
**Status:** IMPLEMENTED — a fresh real-face recalibration is required to collect pose
**Bead(s):** none
**Epic:** none
**Chain:** `standalone-08a28c4a` seq `7`
**Parent:** `HANDOFF_eyelens-eye-only-model_2026-11-09.md`
**Prior code commit:** `fcc4b60` / follow-up `1cfe01f`, tag `v0.6.0`

---

## The Goal

The user asked:

> “our model should catch head position and recalculate all the dots of
> calibrating”

So: the model should be aware of head position/pose and adjust the screen
mapping when the head moves, instead of only working in the exact calibration
posture.

## What Was Built

### Head pose data

- `FaceLandmarkerOptions` now has
  `output_facial_transformation_matrixes=True`.
- `features.extract_head_pose()` turns MediaPipe's 4×4 face transform into six
  values:
  - face forward vector: `R[0,2], R[1,2], R[2,2]`
  - head translation: `tx, ty, tz`
- `TrackerSnapshot` carries `head_pose`; `EyeTracker.recent_head_pose()`
  returns a median pose over the correction hold window.

### Calibration

- Every collected sample now stores its head pose alongside the eye features.
- `CalibrationWindow` filters poses with the same MAD/outlier mask as features.
- The primary eye-only model is fitted first.
- After the 9 validation points are collected, a **global ridge pose correction**
  is fitted from the primary head poses to the primary residuals.
- The correction is accepted only if it improves the independent validation by
  **at least 3% and 5 px**. Otherwise `pose_weight = 0` and the eye-only model
  is used unchanged.
- The final model refits on all 34 points with the selected pose alpha/weight.

### Runtime

- `GazeModel.predict(features, head_pose)` applies:
  - eye-only base prediction
  - optional global head-pose correction
  - local mouse-drag correction
- As the head moves, the pose correction changes, which effectively
  recalculates the whole mapping for the new head position.
- `GazeEngine` passes `snap.head_pose` to `predict`.
- Mouse corrections capture the median head pose at the drop point, so new
  corrections stay consistent with the pose-corrected base.
- `CalibrationMetrics`/summary show **head pose** when compensation is active.

### Persistence / migration

- New calibration files store `pose_samples`, `pose_alpha`, and `pose_weight`.
- `load()` refits the base + pose correction deterministically.
- Old calibrations without pose data still load eye-only (`pose_weight = 0`).
- **A fresh recalibration is required** to collect pose and potentially enable
  the correction.

## Verification Done

| Check | Result |
| --- | --- |
| `ruff check .` | clean |
| `pytest` | 34 passed |
| `compileall` | clean |
| `python -m eyelens --smoke-test` | exit 0 |
| synthetic pose-dependent bias | pose correction selected when it improved validation; model prediction followed the synthetic pose offset |
| synthetic pose calibration E2E | reached RESULT, 34 points, 544 samples, pose samples stored |
| pose save/load | loaded model reproduces pose-corrected prediction |
| tracker pose tests | extraction, median pose, missing pose behaviour |
| old calibration load | still eye-only, no pose correction |

**Not verified:** real-face pose correction selection and the actual benefit on
this user. The current saved calibration predates pose collection, so the app
will load it eye-only. The user must recalibrate once.

## Key Decisions

- **Pose as a global correction, not raw features.** Raw head/face features
  made held-out accuracy much worse (v0.6 diagnosis). A small, strongly
  regularised global correction is fitted on top of the eye-only base and is
  only enabled when the 9 held-out points confirm it helps.
- **Selection guard.** 3% + 5 px minimum improvement prevents enabling a
  noise-level correction. The alpha grid is only `[0.1, 1, 10]` to limit
  validation overfitting.
- **Pose translation + forward vector.** These capture both head position and
  orientation; the model standardises them. The translation is in MediaPipe's
  canonical units and is consistent per user.
- **Eye-only base retained.** The pose layer is optional. If a user’s head pose
  is stable or pose does not help, the eye-only model is still used.
- **Fresh calibration needed.** Old calibrations have no pose samples; they
  cannot retroactively enable the correction.

## Files Changed

- `eyelens/gaze/features.py` — `HEAD_POSE_FEATURES`, `extract_head_pose`.
- `eyelens/gaze/tracker.py` — transform output, `head_pose` snapshot,
  `recent_head_pose`.
- `eyelens/gaze/model.py` — `PoseCorrection`, `fit_pose_correction`,
  `POSE_ALPHAS`, pose fit/predict/persistence, metrics.
- `eyelens/ui/calibration_window.py` — pose collection/filtering, primary/
  validation pose selection, result wording.
- `eyelens/gaze/engine.py` — pass head pose to prediction.
- `eyelens/app.py` — correction hold passes median head pose.
- `README.md` — head-pose compensation, recalibration note.
- `tests/test_features.py`, `tests/test_tracker.py`, `tests/test_model.py`.
- `pyproject.toml`, `eyelens/__init__.py` — version 0.7.0.

## What the User Should Do

1. **Restart eyeLens** (old calibration still loads eye-only).
2. **Recalibrate once** to collect head pose. Keep the head still; the
   “Head moved” warning still applies.
3. On the result screen, look for **head pose** in the summary. If present, the
   pose correction improved the held-out check and is active. If absent, the
   eye-only model was better for this data.
4. Test by moving the head slightly while looking at the same screen point.
5. Re-do mouse corrections after recalibration if needed.

## Where We're Going

1. Real recalibration and check whether `pose_weight` is enabled and how the
   lens behaves when the head moves.
2. If pose correction is not selected but head movement still hurts, the next
   step is a proper 3D gaze/head model (eye position + gaze ray intersection
   with the screen plane), not a linear residual.
3. If pose correction is selected, tune the alpha grid/thresholds and consider
   a small quadratic pose term.
4. Denser calibration grid and crop-based eye landmark inference remain
   options for the ~90–100 px base error floor.

## Quick Start for Next Session

```powershell
cd C:\a_REPOS\eyeLense
# Read: continue_session.md, then this handoff
# Repo: https://github.com/Closegamer/eyeLens (private)
# Branch: main, commit 3586510, tag v0.7.0

.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m eyelens --smoke-test

# Real product
run.bat
# Recalibrate once; inspect the result summary for "head pose".
```

## Session Closed

**Closed at:** 2026-11-09
**Commit:** `3586510` pushed to `origin/main`; tag `v0.7.0` pushed.
**Status:** Implemented and synthetically verified. Real recalibration is the
next acceptance test.
