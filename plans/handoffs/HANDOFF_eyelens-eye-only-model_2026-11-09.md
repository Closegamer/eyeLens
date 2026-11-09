# eyeLens — eye-only model and steadier calibration (v0.6.0)

**Date:** 2026-11-09
**Status:** IMPLEMENTED — real-face recalibration is the next acceptance test
**Bead(s):** none
**Epic:** none
**Chain:** `standalone-08a28c4a` seq `6`
**Parent:** `HANDOFF_eyelens-eye-preview_2026-11-09.md`
**Prior code commit:** `b967f9a`, tag `v0.5.0`

---

## The Goal

The user reported:

> “still bad positioning”

after the zoomed eye preview was added. This session analysed the actual saved
calibration and fixed the real cause of the bad accuracy.

## Diagnosis From the Real Calibration File

The saved file was `%LOCALAPPDATA%\eyeLens\calibration.json`:

- 34 points, 544 samples (16 per point)
- `validation_rmse = 234.0`, `loo_rmse = 101.8`, `worst_point_rmse = 224.3`
- 4 mouse corrections
- Selected model: KRR gamma 0.2, alpha 1.0 (both at the grid edge)

Per-point analysis showed a large slow **head drift** during calibration:

- `face_y` went from ~0.50 at the first centre point to ~0.66 by the last
  points; `head_pitch` went from ~0.69 to ~0.76.
- The 9 validation points were collected after the 25 training points, at the
  drifted head position.
- The model was using raw head/face translation features as part of the gaze
  mapping, so it learned the drift as a gaze cue. When the validation points
  came from a different head position, predictions were 234 px off.

Feature-subset experiments on the same real data:

| Features | LOO | Primary → validation |
| --- | ---: | ---: |
| all 14 (old) | 101.8 | **235.3** |
| iris only (8) | **93.0** | **103.9** |
| iris x/y only (2) | 88.9 | 122.2 |
| iris + head pose proxies | 100.9 | 131.2 |
| iris + face x/y | 93.9 | 183.1 |

A KRR grid search on the eye features bottomed out around 101 px validation;
the remaining error is data/head-drift noise, not model capacity.

## What Changed

- **The fitted gaze model now uses only the 8 eye-in-head features**
  (`iris_rx/ry/lx/ly`, `iris_x/y`, `iris_dx/dy`).
  - Full 14-value vectors remain in the saved calibration for diagnostics and
    for the head-still warning.
  - `MODEL_MODE = "iris8"` is saved with each model.
  - `GazeModel.predict` masks the non-model features before fitting/predicting.
  - Drag corrections are also distance-matched in the eye-only feature space.
- **Existing calibration migration**:
  - Old calibration files are refitted with the eye-only model on load.
  - Their stale `validation_rmse` (measured on the old all-feature model) is
    dropped; the UI shows the fresh LOO estimate instead.
  - Their drag corrections are dropped because their offsets were relative to
    the old base model and would be wrong on the new base.
  - On this machine the existing calibration now loads as
    **“Good · ±93 px”** instead of 234 px, without recalibrating.
- **Calibration dot order is now centre-first plus a fixed shuffle**:
  - Slow head drift is spread across the screen instead of correlating with
    target position.
- **Live head-drift warning**:
  - The first accepted (centre) point defines a head baseline.
  - During SETTLE/SAMPLE the window compares head yaw/pitch/roll and face
    x/y/size to that baseline.
  - If the drift exceeds thresholds, the header and bottom hint show
    **“Head moved — return to your starting head position”**.
  - Sample collection pauses until the head returns; the point is retried.
- Version bumped to `0.6.0`.

## Verification Done

| Check | Result |
| --- | --- |
| `ruff check .` | clean |
| `pytest` | 31 passed |
| `compileall` | clean |
| `python -m eyelens --smoke-test` | exit 0 |
| synthetic calibration E2E | still reaches RESULT with 34 points |
| old real calibration load | refits eye-only, LOO 93.0, validation 0 (estimated), corrections dropped |
| head/face ignored test | changing head/face features does not change predictions |
| old-model migration test | missing `model_mode` falls back to LOO estimate |

**Not verified:** a fresh real-face calibration with the shuffled order and
head-drift warning. That is the next test.

## Files Changed

- `eyelens/gaze/features.py` — `MODEL_FEATURE_INDICES`, `MODEL_MODE`,
  `select_model_features`.
- `eyelens/gaze/model.py` — eye-only fit/predict, masked corrections,
  `model_mode` persistence, old-calibration migration.
- `eyelens/ui/calibration_window.py` — shuffled order, head baseline, warning,
  sample gating, retry message.
- `eyelens/app.py` — “Estimated accuracy” label for migrated models.
- `README.md` — eye-only model, shuffled calibration, head warning.
- `tests/test_model.py` — head/face ignored, old-mode migration.
- `pyproject.toml`, `eyelens/__init__.py` — version 0.6.0.

## What the User Should Do

1. **Restart eyeLens**. The existing calibration is refitted with the eye-only
   model and should immediately be better (estimated ±93 px instead of 234).
2. Try the lens. If it is still off, **recalibrate** to get the new shuffled
   order and head-drift warning.
3. During calibration, watch for **“Head moved”**; return to the starting
   position. The zoomed EYES panel should help.
4. Re-do any mouse corrections (`Ctrl+Alt+D`) after recalibration; the old
   corrections were discarded because they were relative to the old base.

## Where We're Going

1. Real-face recalibration and report the new result.
2. If accuracy is still not enough, the next options are:
   - a denser 6×6 or 7×7 calibration grid (more data, ~70–100 s);
   - MediaPipe facial-transformation-matrix/head-pose features for a proper
     3D head-pose-aware model;
   - crop-based landmark inference on the eye region for more iris pixels.
3. Real-face mouse-correction quality still needs a desktop test.

## Quick Start for Next Session

```powershell
cd C:\a_REPOS\eyeLense
# Read: continue_session.md, then this handoff
# Repo: https://github.com/Closegamer/eyeLens (private)
# Branch: main, commit fcc4b60, tag v0.6.0

.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m eyelens --smoke-test

# Real product
run.bat
# Restart -> existing calibration refits eye-only. Then recalibrate if needed.
```

## Session Closed

**Closed at:** 2026-11-09
**Commit:** `fcc4b60` pushed to `origin/main`; tag `v0.6.0` pushed.
**Status:** Implemented and verified offline. A fresh real-face calibration is
the remaining acceptance test.
