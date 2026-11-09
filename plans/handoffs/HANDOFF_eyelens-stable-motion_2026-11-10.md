# eyeLens — stable+motion calibration and eye-only model (v0.8.0)

**Date:** 2026-11-10
**Status:** IN PROGRESS — implemented; real stable+motion recalibration pending
**Bead(s):** none
**Epic:** none
**Chain:** `standalone-08a28c4a` seq `8`
**Parent:** `HANDOFF_eyelens-head-pose_2026-11-09.md`
**Prior chain:** `HANDOFF_eyelens-mvp_2026-11-09.md` > `HANDOFF_eyelens-calibration-v2_2026-11-09.md` > `HANDOFF_eyelens-mouse-correction_2026-11-09.md` > `HANDOFF_eyelens-shapes-big-lens_2026-11-09.md` > `HANDOFF_eyelens-eye-preview_2026-11-09.md` > `HANDOFF_eyelens-eye-only-model_2026-11-09.md` > `HANDOFF_eyelens-head-pose_2026-11-09.md` > this

---

## Stale References

- `GazeModel.pose_samples` — not found in the current codebase. It was removed
  in seq 8; the model now stores reusable `PoseCorrection` coefficients in
  `pose_correction`.
- `CalibrationWindow._available_pose_samples` — not found; replaced by
  `_motion_arrays()` because pose data now comes from a dedicated head-motion
  sample set.
- JSON key `pose_samples` — no longer written by v0.8; v0.7 pose files that
  only have `pose_samples` are rejected.

## Since Last Handoff

- v0.7 planned a real recalibration to collect head pose. The user did it; the
  resulting held-out error was **262 px**, worse than the pre-pose attempt.
- The v0.7 pose correction was enabled (weight 1.0, alpha 0.1) but only improved
  the primary model's validation from ~267 to ~252–262 px. The data did not
  contain within-target pose variation, so the correction could not learn a
  real head-pose effect.
- The v0.6 change to a shuffled dot order turned out to be a serious regression:
  several dots were mislooked, producing eye-feature outliers of hundreds of
  pixels. The prior centre-out eye-only data gave ~104 px validation.
- v0.8 restores centre-out order, adds a stable-head + head-motion split per
  dot, stores the fitted pose correction as reusable coefficients, and adds a
  quality gate that refuses to save a bad calibration.
- The current machine calibration is a v0.7 pose file; it is deliberately
  rejected on load. The next session/user must recalibrate with the new
  protocol.

## Reference Documents

- `README.md` — product overview, stable+motion calibration, controls, architecture.
- `models/README.md` — MediaPipe model source and license.
- `plans/handoffs/HANDOFF_eyelens-eye-only-model_2026-11-09.md` — real-data
  feature-subset diagnosis that led to the eye-only model.
- `plans/handoffs/HANDOFF_eyelens-head-pose_2026-11-09.md` — v0.7 pose attempt
  and why it failed.

## The Goal

Build **eyeLens**, a click-through always-on-top magnifying lens that follows the
user's gaze from an ordinary webcam. The user has repeatedly rejected
calibration accuracy: the lens must point at what the user is actually looking
at, not merely at the calibration dots, and it must stay accurate when the head
moves. The MVP mechanics are done; the remaining work is a reliable
personal-calibration mapping.

## Where We Are

- Version **0.8.0**, code commit `302e6b2`, tag `v0.8.0`; memory commit
  `635a9e1` (handoff/continue files) is on `main`.
- **Current saved calibration is rejected**: the file in
  `%LOCALAPPDATA%\eyeLens\calibration.json` is a v0.7 pose calibration with no
  reusable motion-based correction. `GazeModel.load()` returns `None`; the app
  reports “older/damaged; recalibration required”.
- **No valid calibration exists on this machine right now.** The next operation
  is a fresh stable+motion recalibration.
- **Eye-only base model** (`GazeModel.fit`) uses only the 8 iris features:
  `iris_rx/ry/lx/ly`, `iris_x/y`, `iris_dx/dy`. The full 14-value vector is kept
  for diagnostics/previews; head/face features are masked out of the base model.
- **Randomised dot order was removed** in v0.8. The latest v0.7 recalibration
  used a shuffle and produced validation **262.5 px**, LOO **132.2 px**, train
  **108.4 px**, worst point **291.8 px**.
- **Centre-out order restored**, settle time **0.65 s**, active target dot
  enlarged (46 px halo, 26 px progress ring, 5.5 px core).
- **Each calibration dot now has two parts**:
  - stable 0.65 s (base training frames);
  - motion 1.0 s (same target, deliberately varied head pose).
  Total sample phase `SAMPLE_SECONDS = 1.65`; calibration ~80 s.
- **Mouse correction** from v0.3 remains: `Ctrl+Alt+D`, drag handle, local
  residual memory; it now captures the median head pose at the drop.
- **Lens UI** from v0.4/v0.5 remains: Round/Square/Wide (1.6×), 120–1200 px
  high, `Ctrl+Alt+B` big lens, and the zoomed EYES preview.
- **Quality gate**: the result screen refuses Enter/Space unless
  `model.quality_ok` (`error_rmse <= 150 px`). Bad calibrations cannot be saved.
- **Testing**: 34 passed, `ruff` clean, `compileall` clean, smoke exit 0.
- **Synthetic E2E**: 34 points, 544 stable samples, validation ~1.1 px; pose
  correction unit test recovers a synthetic 400/300 px pose offset and
  save/load reproduces it.

## What We Tried (Chronological)

1. **MVP build** — PySide6 overlay, MediaPipe tracking, 25-point calibration,
   ridge regression, WDA capture exclusion. Mechanics worked; real accuracy was
   not validated.
2. **Calibration v2** — added a 52-term curated polynomial + KRR residual,
   grouped leave-one-point-out CV, 9-point accuracy check, and an independent
   validation result. Synthetic accuracy roughly halved.
3. **Real calibration diagnosis #1** — old file: validation 234, LOO 102,
   worst 224; feature subsets showed all-14 val 235, iris-only val 104, LOO 93.
   Raw head/face features were learning slow head drift. Switched the fitted
   model to eye-only (v0.6) and added a head-drift warning/shuffled order.
4. **Random order experiment** — intended to decorrelate head drift, but the
   latest real recalibration produced mislooked points and validation 262.5,
   worse than the centre-out eye-only result. Reverted in v0.8.
5. **Head-pose v0.7** — added MediaPipe 6-DOF transform and a global ridge pose
   correction fitted on stable samples. Real data had essentially one head pose
   per target, so the correction could only improve 267→252–262; insufficient.
6. **Stable+motion v0.8** — split each dot into stable and deliberate head-motion
   windows; base on stable frames, pose correction on motion residuals; combined
   validation; quality gate; old v0.7 pose files rejected.
7. **Current state** — no valid calibration; user must run the new 80-second
   protocol. The next data will show whether within-target head motion makes the
   pose correction useful.

## Key Decisions

- **Eye-only base, not raw head/face features.** Real data showed raw head/face
  predictors reduced held-out accuracy from ~104 px to ~234 px. Head pose is used
  only as an optional correction layer.
- **Centre-out, predictable dot order.** The shuffled order was a regression;
  users mislooked randomly placed dots. Centre-out is easier to follow and gave
  the best real data so far.
- **Stable+motion per dot.** This is the only way to get within-target pose
  variation without adding extra calibration points; it lets the pose correction
  learn a real head-position effect instead of time drift.
- **Pose correction must earn its place.** It is fitted on motion residuals and
  enabled only if combined held-out validation improves by 5%/10 px. Otherwise
  the eye-only model is kept.
- **Quality gate.** A calibration with measured error >150 px cannot be
  accepted; otherwise the user keeps ending up with a bad lens.
- **Reject old v0.7 pose files.** They have no reusable correction record; using
  them would leave the lens in the known-bad 262 px state.
- **No crop-based inference yet.** It remains a possible next step but was not
  implemented because the current data quality/protocol was the dominant issue.
- **Keep the drag correction.** It is useful for local residual errors and now
  works with the pose-corrected base.

## Evidence & Data

### Real calibration files

| File/version | Model | Validation | LOO | Train | Worst point | Notes |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Old v0.5 centre-out | all 14 | 234.0 | 101.8 | 65.8 | 224.3 | raw head/face features; 4 corrections |
| Old v0.5 centre-out | iris 8 | ~104 | 93.0 | — | — | feature-subset experiment |
| New v0.7 shuffled | iris8 + pose | **262.5** | 132.2 | 108.4 | 291.8 | pose weight 1.0, alpha 0.1; mislooked dots |
| Current v0.7 file | — | — | — | — | — | **rejected by v0.8 load** |

### Mislooked-point evidence (v0.7 shuffled data)

| Point | Target | Observed iris_y | Neighbour values | Error signal |
| --- | --- | ---: | ---: | --- |
| 17 | 528, 660 | -0.0394 | -0.0579…-0.0612 | ~0.02 feature units |
| 23 | 528, 240 | -0.0713 | -0.0816…-0.0828 | ~0.011 feature units |
| 33 | 1613, 475 | -0.0485 | -0.0582…-0.0587 | ~0.010 feature units |

### Model/protocol constants (v0.8)

| Constant | Value |
| --- | --- |
| Eye feature indices | 0–7 of 14 |
| `GazeModel` ridge alphas | 15 values, 1e-3…1e4 |
| KRR gammas | 0.002…0.2 |
| KRR alphas | 1e-4…10 |
| Pose alpha grid | `[0.1, 1.0, 10.0]` |
| Pose acceptance | ≥5% and ≥10 px combined validation improvement |
| Quality gate | `error_rmse <= 150 px` |
| `SETTLE_SECONDS` | 0.65 |
| `STABLE_SECONDS` | 0.65 |
| `MOTION_SECONDS` | 1.0 |
| `SAMPLE_SECONDS` | 1.65 |
| Calibration points | 25 training + 9 validation |
| Calibration time | ~80 s |
| Lens size | 120–1200 px high; wide = 1.6× |
| Smoothing default | 0.72 |
| Zoom | true magnification, source = diameter / zoom |

### Verification and commits

| Check | Result |
| --- | --- |
| `ruff check .` | clean |
| `pytest` | 34 passed |
| `compileall` | clean |
| `python -m eyelens --smoke-test` | exit 0 |
| synthetic calibration E2E | 34 points, 544 samples, validation 1.1 px |
| pose correction unit test | synthetic 400/300 px offset recovered; save/load identical |
| old v0.7 calibration load | rejected (`None`) |
| current app startup | reports recalibration required |

Recent commits on `main` (v0.8 session):

| Commit | Summary |
| --- | --- |
| `302e6b2` | stable+motion calibration, centre-out order, quality gate (v0.8.0) |
| `635a9e1` | session memory/handoff commit |
| `bebdef8` | v0.7 head-pose session commit |
| `3586510` | head-pose correction (v0.7.0) |
| `cb25e98` | v0.6 follow-up memory |
| `1cfe01f` | repaint head-warning hint |
| `9c622ec` | v0.6 eye-only session commit |
| `fcc4b60` | eye-only gaze model (v0.6.0) |

### Environment

| Item | Value |
| --- | --- |
| OS | Windows 11 24H2-class, 1920×1200 primary |
| Python | 3.12.10, venv `C:\a_REPOS\eyeLense\.venv` |
| Camera | FHD Camera index 0; MSMF 1080p 35 fps / 720p 32 fps tested |
| Repo | `https://github.com/Closegamer/eyeLens` private, `main` |
| Package versions | mediapipe 0.10.35, PySide6 6.12.0, opencv 4.14.0.94, mss 10.2.0 |

## Code Analysis

- `eyelens/gaze/model.py`
  - `MODEL_VERSION = 2`, `FEATURE_VERSION = 2`, `MODEL_MODE = "iris8"`.
  - `MODEL_FEATURE_INDICES = (0..7)`; `select_model_features()` zeros head/face
    before base fit/predict.
  - `GazeModel.fit(samples, targets, point_ids, openness_threshold, screen,
    validation_rmse=..., validation_points=..., corrections=...,
    correction_features=..., correction_offsets=..., motion_samples=...,
    motion_targets=..., motion_point_ids=..., motion_poses=...,
    pose_alpha=..., pose_weight=..., pose_correction=...)`.
  - Base ridge + KRR residual selected by grouped leave-one-point-out CV.
  - `PoseCorrection` stores `mean/std/coef/intercept/clip_low/clip_high/limit`;
    `fit_pose_correction()` fits a ridge from motion pose to residual.
  - `predict(features, head_pose=None)` = base + `pose_weight * pose_correction
    .apply(head_pose)` + local correction; `predict_unclipped()` is used for
    motion fitting.
  - `to_dict` stores `pose_correction`, `pose_alpha`, `pose_weight`, feature
    clip range; `load` rejects old pose files without `pose_correction`.
- `eyelens/ui/calibration_window.py`
  - `GRID_X = (0.05, 0.275, 0.5, 0.725, 0.95)`,
    `GRID_Y_TOP = 0.20`, `GRID_Y_BOTTOM = 0.90`.
  - `_center_out()` order; `PREVIEW_RECT = (24,24,320,150)`,
    `FACE_PILL_RECT = (24,184,260,28)`.
  - Stable/motion sampling split; `_filter_samples(filter_head=...)` with
    4.25/4.0σ for stable and 6.0/5.5σ on iris dims for motion.
  - `_select_pose_correction()` fits on primary motion residuals and evaluates
    combined stable+motion validation; threshold 5%/10 px.
  - `_accept()` and `keyPressEvent` enforce quality `<=150 px`.
- `eyelens/gaze/tracker.py`
  - `FaceLandmarkerOptions(output_facial_transformation_matrixes=True)`.
  - `TrackerSnapshot.head_pose` (6 values); `recent_head_pose()` median.
  - Eye preview crop is separate; `EYE_PREVIEW_WIDTH=640`, height 300.
- `eyelens/gaze/engine.py` — `prediction = self.model.predict(snap.features,
  snap.head_pose)`.
- `eyelens/app.py` — `_learn_correction()` passes `recent_head_pose()` into
  `with_correction`; status label “Estimated accuracy” for migrated models.
- `eyelens/gaze/features.py` — `HEAD_POSE_FEATURES`, `extract_head_pose()`,
  `select_model_features()`.

## Files Changed

### Source code

- `eyelens/gaze/model.py` — eye-only base, motion pose fit, `PoseCorrection`
  persistence, clip persistence, old pose rejection.
- `eyelens/ui/calibration_window.py` — centre-out order, 0.65 s settle, stable/
  motion split, motion filters, combined validation, quality gate, stronger
  target, dynamic hints.
- `eyelens/gaze/tracker.py` — face transformation matrix output, `head_pose`
  snapshot, `recent_head_pose`.
- `eyelens/gaze/features.py` — head pose extraction, model feature mask.
- `eyelens/gaze/engine.py` — pass head pose to prediction.
- `eyelens/app.py` — correction hold captures head pose; 80 s detail text.
- `eyelens/ui/settings_window.py` — 80 s stable+motion help; version v0.8.
- `eyelens/hotkeys.py` — unchanged from v0.3/v0.4 (`Ctrl+Alt+D`, `Ctrl+Alt+B`).

### Tests

- `tests/test_model.py` — eye-only mask, old-mode migration, pose motion fit,
  save/load, local corrections.
- `tests/test_tracker.py` — head pose extraction/recent median, eye crop,
  recent feature filtering.
- `tests/test_features.py` — roll invariance, head pose extraction.
- `tests/test_settings.py` — shape/lens dimensions/big diameter.
- `tests/test_capture.py` — true zoom source extent.

### Data & evidence

- `%LOCALAPPDATA%\eyeLens\calibration.json` — current file is a v0.7 pose
  calibration; **will be rejected** by v0.8. A new calibration will overwrite it.
- `%LOCALAPPDATA%\eyeLens\settings.json` — schema 2, defaults.
- Temp diagnostic scripts (not in repo):
  `C:\Users\avgrigorev\AppData\Local\Temp\opencode\calibration_diag*.py`,
  `feature_subset_diag.py`, `poly_mapping_diag.py`, `per_eye_diag.py`,
  `krr_grid_diag.py`.

### Config

- `pyproject.toml`, `eyelens/__init__.py` — version 0.8.0.
- `README.md` — 80 s stable+motion calibration, eye-only model, head pose,
  quality gate, troubleshooting.

## User Feedback & Preferences (REQUIRED)

- “zoom must be zoom IN - not zoom out.”
- “calibration works very bad - need to make it much better.”
- “reactiveness of lens should be slower - not to fast.”
- “we have to make trained model - when lens holds wrong position - user can
  take it with a mouse and put to right poritin so model will train this
  quickly.”
- “lens should have bigger size on demand.”
- “it must be choise - round lense or square or wide square.”
- “make eyes of user zoomed much when calibrating - we need more accurate
  positioning.”
- “our model should catch head position and recalculate all the dots of
  calibrating.”
- “still bad positioning” after the first real calibration.
- “still bad positioning after calibrating” after the v0.7 recalibration.
- “handoff” (this request).
- Global preference: **never ask the user to paste handoffs/prompts**. Write
  memory files and let the next session read them automatically. Do not print a
  paste block.
- The user is clearly frustrated by repeated recalibration failures; next
  sessions should be decisive and verify real-data numbers, not just synthetic
  tests.

## Where We're Going

1. **Run the stable+motion recalibration** (`run.bat` → Calibrate). Hold still
   for the first part of each dot, then slowly move the head left/right while
   keeping eyes on the dot. It takes ~80 s.
2. **Check the result**: measured error must be ≤150 px to accept; if not, press
   R. Look for **head pose** in the summary. Record the validation error and
   whether pose is active.
3. **Test head movement**: look at a fixed point and move the head a little; if
   the lens follows, the motion correction is working. Re-do mouse corrections
   with `Ctrl+Alt+D` if there are local errors.
4. If the result is still >150 px or still feels bad:
   - try a **6×6 or 7×7 calibration grid** (more data, ~100 s);
   - make the motion part an explicit left-right + up-down pattern;
   - implement a proper **3D gaze/head model** (eye position + gaze ray
     intersection with the screen plane) instead of a linear pose residual;
   - consider crop-based eye landmark inference.
5. Re-test the **mouse correction handle** on the real desktop (v0.3 feature;
   only synthetically tested).

## Risks & Blockers

- The stable+motion protocol is **not yet tested on a real face**. It is the
  best hypothesis from the real-data diagnosis, but it could still produce a
  poor validation. The quality gate prevents saving a bad result, but the user
  may have to retry.
- The current machine has **no valid calibration**; the app will start
  “Not calibrated”. The old v0.7 file is intentionally rejected.
- The 80 s calibration is longer; head drift/fatigue may affect the later dots.
  Centre-out + stable/motion + the head warning are the mitigations.
- The head-motion part may be hard to follow; if the user moves too much, the
  motion samples/motion validation can be noisy.
- The linear pose correction may be insufficient for large head movement; a 3D
  model remains the fallback.
- Real Windows mouse drag of the correction handle is still unverified.

## Open Questions

- Does within-target head motion actually improve the combined validation, or
  will pose_weight remain 0?
- Is the eye-only ~100 px floor irreducible without crop-based inference or a
  3D gaze model?

## Quick Start for Next Session

```powershell
cd C:\a_REPOS\eyeLense
# Read: continue_session.md, then this handoff
# Repo: https://github.com/Closegamer/eyeLens (private)
# Branch: main, commit 302e6b2, tag v0.8.0

# Verify toolchain
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m eyelens --smoke-test

# Real product
run.bat
# Calibrate: hold still, then slowly move head left/right on every dot.
# Check the result error and whether "head pose" is shown.
# If >150 px, Enter is disabled; press R and retry.

# Key files
#   eyelens/gaze/model.py
#   eyelens/ui/calibration_window.py
#   eyelens/gaze/tracker.py
#   eyelens/gaze/features.py

# Evidence
#   %LOCALAPPDATA%\eyeLens\calibration.json (will be overwritten by new calibration)
#   %LOCALAPPDATA%\eyeLens\settings.json

# Next action
#   Complete the stable+motion recalibration and record the validation error
#   and pose_weight. This is the decisive test of v0.8.
```
