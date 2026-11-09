# eyeLens — stable+motion calibration (v0.8.0)

**Date:** 2026-11-10
**Status:** IMPLEMENTED — a fresh stable+motion recalibration is required
**Bead(s):** none
**Epic:** none
**Chain:** `standalone-08a28c4a` seq `8`
**Parent:** `HANDOFF_eyelens-head-pose_2026-11-09.md`
**Prior code commit:** `3586510`, tag `v0.7.0`

---

## The Goal

The user reported:

> “still bad positioning after calibrating”

after the v0.7 head-pose attempt. The latest saved calibration was analysed to
find why, and the calibration protocol was changed again.

## Diagnosis of the Latest Calibration

Latest `calibration.json` (v0.7 recalibration):

- `validation_rmse = 262.5`, `loo_rmse = 132.2`, `train_rmse = 108.4`
- `worst_point_rmse = 291.8`
- pose correction enabled: weight 1.0, alpha 0.1
- 34 points, 533 stable samples, 0 corrections

Problems found:

1. The **shuffled/random dot order** (introduced in v0.6) produced several
   mislooked points. Examples:
   - point 17 (528, 660): `iris_y = -0.039` while the other y=660 points were
     -0.058 to -0.061
   - point 23 (528, 240): `iris_y = -0.071` while the other y=240 points were
     -0.082
   - point 33 (1613, 475): `iris_y = -0.049` while the other y=475 points were
     -0.058
   These are hundreds of pixels of feature error and cannot be fixed by a
   better model.
2. The prior centre-out calibration (v0.5 data) gave eye-only validation
   **~104 px**, much better than 267 px on the shuffled data.
3. The v0.7 head-pose correction was fitted on stable samples only, where each
   target had essentially one head pose. There was no within-target pose
   variation, so the correction could not learn a meaningful head-pose effect.
   It only improved 267 → 252–262, not enough.
4. The user's head was actually fairly stable in the new data; the eye mapping
   data quality was the dominant problem, not head drift.

## What Changed

- **Restored the predictable centre-out dot order** (removed the fixed shuffle).
- **Raised settle time** from 0.50 to 0.65 s.
- **Each dot now has two parts**:
  1. **Stable part** (0.65 s): hold still; these frames train the base eye-only
     model.
  2. **Motion part** (1.0 s): keep looking at the dot and slowly move your head
     a little left and right. These frames have the same target under varying
     head pose and train the head-pose correction.
- The calibration window now shows a dynamic hint:
  - “Hold your gaze — sampling stable position…”
  - then “Keep your eyes on the dot — slowly move your head left and right…”
- The head-moved warning is active only during the stable part; it is
  intentionally silent while the user moves their head.
- `GazeModel.fit` now takes separate `motion_samples`, `motion_targets`,
  `motion_point_ids`, `motion_poses`:
  - base model = stable frames;
  - pose correction = ridge fit on the motion-frame residuals (same target,
    varied head pose);
  - the pose correction is stored as reusable coefficients
    (`pose_correction`) in `calibration.json`, not as raw motion samples.
- The correction is accepted only if the **combined stable+motion validation**
  improves by at least **5% and 10 px**; otherwise the eye-only model is used.
- The feature clip range now includes motion features and is saved/restored.
- **Quality gate**: the result screen no longer accepts Enter/Space unless the
  measured error is at least “Good” (≤150 px). A bad calibration cannot be
  saved; press R to retry.
- **Old v0.7 pose calibrations are rejected** because they have no usable
  motion-based correction record. The current saved calibration will show
  “recalibration required” on startup.
- The active calibration dot is larger/brighter with a bigger progress ring.
- Version bumped to `0.8.0`.

## Verification Done

| Check | Result |
| --- | --- |
| `ruff check .` | clean |
| `pytest` | 34 passed |
| `compileall` | clean |
| `python -m eyelens --smoke-test` | exit 0 |
| synthetic calibration E2E | 34 points, stable path, validation 1.1 px, accepts result |
| synthetic pose correction unit test | pose-dependent 400/300 px offset recovered; save/load reproduces |
| old v0.7 calibration load | rejected (`None`), forcing recalibration |
| app smoke with old file | reports “older/damaged; recalibration required” |

**Not verified:** a real stable+motion calibration and the actual benefit of the
within-target head-motion correction. That is the next and decisive test.

## Files Changed

- `eyelens/ui/calibration_window.py` — centre-out order, settle 0.65, stable/
  motion split, motion filtering, pose selection on motion frames, combined
  validation, dynamic hints, stronger target, quality gate.
- `eyelens/gaze/model.py` — motion-based pose fit, reusable `PoseCorrection`
  persistence, clip range persistence, old pose calibration rejection.
- `eyelens/ui/settings_window.py` — 80-second/stable-motion help text.
- `eyelens/app.py` — 80-second calibration detail.
- `README.md` — stable+motion instructions, quality gate, head-pose explanation.
- `tests/test_model.py` — pose test updated to motion API.
- `pyproject.toml`, `eyelens/__init__.py` — version 0.8.0.

## What the User Should Do

1. Restart eyeLens. The old calibration will be rejected; the settings window
   should say “Not calibrated” / “recalibrate”.
2. Click **Calibrate**. It takes about **80 seconds**.
3. For each dot:
   - hold your head still for the first part (the hint says “sampling stable
     position”),
   - then keep your eyes on the dot and slowly move your head a little left and
     right for the second part.
4. The result screen will show a combined stable+motion error. If it is not
   “Good” (≤150 px), Enter is disabled; press R and try again.
5. Check whether the summary says **head pose**. If yes, the motion correction
   improved the held-out accuracy and is active.

## Where We're Going

1. Real stable+motion recalibration; report the validation error and whether
   `head pose` is active.
2. If the motion part is hard to follow, adjust `MOTION_SECONDS`/hint copy.
3. If the combined error is still >150, try:
   - a denser 6×6 grid;
   - a more explicit motion pattern (left-right + up-down) per dot;
   - a proper 3D gaze/head model instead of a linear pose residual.
4. If the old v0.7 calibration is rejected and the user wants it back, it is
   gone; the new protocol is required.

## Quick Start for Next Session

```powershell
cd C:\a_REPOS\eyeLense
# Read: continue_session.md, then this handoff
# Repo: https://github.com/Closegamer/eyeLens (private)
# Branch: main, commit 302e6b2, tag v0.8.0

.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m eyelens --smoke-test

# Real product
run.bat
# Recalibrate: hold still, then move head slowly left/right on each dot.
```

## Session Closed

**Closed at:** 2026-11-10
**Commit:** `302e6b2` pushed to `origin/main`; tag `v0.8.0` pushed.
**Status:** Implemented and synthetically verified. Real stable+motion
recalibration is the next acceptance test.
