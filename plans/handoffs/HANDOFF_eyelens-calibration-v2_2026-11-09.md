# eyeLens — calibration v2, true zoom-in, calmer lens follow

**Date:** 2026-11-09
**Status:** IMPLEMENTED — awaiting real-face calibration on this machine
**Bead(s):** none
**Epic:** none
**Chain:** `standalone-08a28c4a` seq `2`
**Parent:** `HANDOFF_eyelens-mvp_2026-11-09.md`
**Prior chain:** MVP handoff, commit `44701b0`, tag `v0.1.0`

---

## The Goal

The user reported three concrete problems after trying the MVP:

1. **“zoom must be zoom IN - not zoom out.”**
2. **“calibration works very bad - need to make it much better.”**
3. **“reactiveness of lens should be slower - not to fast.”**

This session fixed all three. The code is committed and pushed as
`7de4db4` (`fix: true zoom-in, calmer lens, stronger calibration`), tagged
`v0.2.0`. The only remaining item is a real-face calibration on this machine.

## Where We Are

- Fixed the zoom geometry: the lens was sampling `diameter * zoom` and drawing
  it into `diameter`, which is minification. It now samples
  `diameter / zoom`, so 2× is real 2× magnification. The same helper
  (`source_extent`) is used by the capture thread and the painter.
- Slowed the lens follow substantially:
  - Default smoothing is now `0.72` (was `0.55`).
  - 1€ filter cutoff range is now 2.4 Hz → 0.22 Hz (was 4.0 → 0.42 Hz).
  - Filter beta is 0.030 → 0.004 (was 0.045 → 0.008).
  - Overlay centre easing is now 85 ms (was 22 ms).
  - The old “snap to gaze when visibility is low” behaviour was removed, so
    the lens glides after a blink instead of jumping.
- Rebuilt calibration around a **hybrid model**:
  - 52-term curated polynomial ridge (was 40 terms).
  - RBF kernel-ridge residual model, enabled only when grouped
    leave-one-point-out CV says it beats the polynomial by ≥1%.
  - Exact grouped-LOO for KRR via a block-inverse identity, so the fit stays
    fast (≈1.3 s for 400 samples, ≈2 s for 544).
  - Samples are capped at 16 per target (closest to the target median) to
    bound fit cost and reduce correlated noise.
- Fixed two feature bugs:
  - `head_roll` was computed from `right_eye - left_eye` (≈π) and then clipped
    to a constant `0.8`. It now uses `left - right`, so it is a real signal.
  - Vertical iris position and openness were normalised by raw eyelid height.
    They are now measured in a rotated eye frame, so head tilt does not fake
    vertical gaze or a blink. `iris_y` is the perpendicular iris offset from
    the canthus line / eye width.
  - Replaced the distance-invariant `face_scale` with `face_size` (apparent
    face width / frame width), a real camera-distance proxy.
- Added a **9-point accuracy check** after the 25 training points:
  - Green dots, “check N / 9” progress.
  - The primary model is fitted on 25 points only, then predicts the 9 held-out
    points. The result screen shows this real held-out error.
  - The final model is then fitted on all 34 points.
  - Result screen: “Checked on 9 independent points (34 points, 544 samples)”.
- Calibration target order is now centre-out, which distributes slow head drift
  across screen positions instead of coupling it to row order.
- `Settings` schema is now 2; old settings files are migrated once to the new
  calmer smoothing default. Old calibration files are rejected (feature/model
  version bump) and the app tells the user to recalibrate.
- Version bumped to `0.2.0`.

## Verification Done

| Check | Result |
| --- | --- |
| `ruff check .` | clean |
| `pytest` | 23 passed |
| `compileall` | clean |
| `python -m eyelens --smoke-test` | exit 0 |
| synthetic two-stage calibration E2E | reached RESULT, 34 points, 544 samples, validation RMSE 1.2 px (fake linear tracker) |
| KRR nonlinear synthetic fit | KRR selected; LOO RMSE 4.9 px |
| model fit time | ≈1.3 s for 400 samples; load ≈1.3 s |
| live camera smoke run | tracker opened, no face in front of the camera, no crash |

**Not verified:** real-face accuracy on this machine. This is the first thing
the next session or the user should do.

## What We Tried / Key Decisions

- **True zoom vs. “zoom out”:** The original code multiplied the source extent
  by zoom. That is the opposite of magnification. Fixed in one shared helper so
  capture and paint cannot disagree.
- **Slower by default vs. exposing a new slider:** Reused the existing
  smoothing slider, changed its mapping and default, and updated the tooltip.
  The user can still make it faster.
- **Ridge vs. KRR vs. hybrid:** Synthetic experiments with nonlinear gaze and
  head-pose coupling showed the hybrid roughly halving error versus polynomial
  ridge alone (≈55 px → ≈26 px in one test). Pure KRR was sometimes better than
  ridge but less stable; the residual formulation falls back to the polynomial
  far from calibration data.
- **Full quadratic vs. curated expansion:** Kept a curated expansion but added
  head-roll, face-size and distance interactions; the KRR residual supplies the
  remaining local nonlinearity.
- **All frames vs. cap:** Capped to 16 frames per target, closest to the median.
  This keeps the kernel stage fast and removes correlated noise. The fake E2E
  confirmed the cap (1577 collected → 544 used).
- **Validation points:** The validation points are not used to fit the primary
  model, so the reported error is a real held-out measurement. The final model
  then includes them, so actual use should be at least as good as reported.
- **Rejected for now:** MediaPipe facial transformation matrix features. The
  current head yaw/pitch proxies are still crude; pose-matrix features are the
  most likely next accuracy improvement if real testing still shows drift.
  Adding them is a feature-version bump and needs a real-face test.

## Files Changed

- `eyelens/capture.py` — `source_extent()`; true magnification source size.
- `eyelens/ui/overlay.py` — uses `source_extent`; 85 ms centre easing; no
  visibility snap.
- `eyelens/gaze/engine.py` — calmer smoothing mapping.
- `eyelens/config.py` — default smoothing 0.72; settings schema 2 migration.
- `eyelens/gaze/features.py` — feature version 2; roll-corrected eye frame;
  fixed head roll; `face_size`; 52-term expansion.
- `eyelens/gaze/model.py` — model version 2; hybrid ridge + KRR residual;
  grouped CV; sample cap; validation metrics; `error_rmse`.
- `eyelens/ui/calibration_window.py` — 25 + 9 two-stage flow; centre-out order;
  green accuracy-check dots; primary/final fit stages; validation RMSE.
- `eyelens/app.py` — `error_rmse` in OSD/tray/notifications; old calibration log.
- `eyelens/ui/settings_window.py` — new copy, v0.2, smoothing labels, accuracy.
- `README.md` — true zoom, 25 + 9 calibration, hybrid model, smoothing guidance.
- `tests/test_capture.py` — zoom is magnification, not minification.
- `tests/test_features.py` — roll-invariance test.
- `tests/test_model.py` — validation error, hybrid nonlinear test, save/load.
- `pyproject.toml`, `eyelens/__init__.py` — version 0.2.0.

## User Feedback & Preferences (REQUIRED)

- “zoom must be zoom IN - not zoom out.”
- “calibration works very bad - need to make it much better”
- “reactiveness of lens should be slower - not to fast”
- Global preference: never ask the user to paste handoffs/prompts; write memory
  files and let the next session read them automatically.

## Where We're Going

1. **Run a real-face calibration** with the FHD camera (index 0):
   `run.bat`, then Calibrate. The result screen should now show a held-out
   error in px. Record it.
2. If the measured error is still high (>150 px) or the lens drifts:
   - Inspect `%LOCALAPPDATA%\eyeLens\calibration.json` metrics:
     `validation_rmse`, `loo_rmse`, `krr_weight`, `krr_gamma`, `worst_point_rmse`.
   - Check whether the user moves their head during use. If yes, implement
     MediaPipe facial-transformation-matrix features (head yaw/pitch/roll and
     distance) as feature version 3.
   - Consider raising `_MAX_SAMPLES_PER_POINT` to 24 if the KRR stage is
     underfitting (fit cost still acceptable).
3. If the lens feels too slow, lower the Smoothing slider; if it still jitters,
   raise it.
4. Then continue the MVP roadmap: camera pause/privacy toggle, multi-monitor,
   packaging, lens shapes.

## Quick Start for Next Session

```powershell
cd C:\a_REPOS\eyeLense
# Read: continue_session.md, then this handoff
# Repo: https://github.com/Closegamer/eyeLens (private)
# Branch: main, commit 7de4db4, tag v0.2.0

.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m eyelens --smoke-test

# Real product
run.bat

# Key files for accuracy work
#   eyelens/gaze/features.py
#   eyelens/gaze/model.py
#   eyelens/ui/calibration_window.py
#   eyelens/gaze/engine.py
#   eyelens/ui/overlay.py

# Evidence
#   %LOCALAPPDATA%\eyeLens\settings.json   (now schema 2)
#   %LOCALAPPDATA%\eyeLens\calibration.json (after real calibration)
```

## Session Closed

**Closed at:** 2026-11-09
**Commit:** `7de4db4` (pushed to `origin/main`), tag `v0.2.0` pushed.
**Status:** Code complete and verified synthetically. A real-face calibration
is the remaining acceptance test.
