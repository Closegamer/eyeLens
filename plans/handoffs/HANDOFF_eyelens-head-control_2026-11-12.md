# eyeLens — head-controlled lens (v0.9.0)

**Date:** 2026-11-12
**Status:** IMPLEMENTED — real head calibration pending
**Chain:** `standalone-08a28c4a` seq `9`
**Parent:** `HANDOFF_eyelens-stable-motion_2026-11-10.md`
**Prior chain:** `HANDOFF_eyelens-mvp_2026-11-09.md` > `HANDOFF_eyelens-calibration-v2_2026-11-09.md` > `HANDOFF_eyelens-mouse-correction_2026-11-09.md` > `HANDOFF_eyelens-shapes-big-lens_2026-11-09.md` > `HANDOFF_eyelens-eye-preview_2026-11-09.md` > `HANDOFF_eyelens-eye-only-model_2026-11-09.md` > `HANDOFF_eyelens-head-pose_2026-11-09.md` > `HANDOFF_eyelens-stable-motion_2026-11-10.md` > this

---

## Request

> “make lense control by the head but not by eyes - then we will have more control on it”

The user asked for a decisive pivot away from iris gaze.  Head control is now
the default.  Eye control is retained only as an optional fallback in Settings.

## What Changed

- **Head control is the default.**
  - `GazeModel.control_mode == "head"` fits only the six gaze-independent
    head/face features: `head_yaw`, `head_pitch`, `head_roll`, `face_x`,
    `face_y`, `face_size` (feature indices 8–13).
  - Iris features are zeroed before fitting and prediction.  Looking around,
    blinking, or closing the eyes does not move or freeze the lens.
- **Eye control remains available.**
  - Settings → **Control** offers **Head** (default) and **Eyes**.
  - Eye mode still uses the eight iris features and the v0.8 stable+motion
    protocol.
  - Switching mode invalidates the current calibration, hides the lens, and
    asks for recalibration in the new mode.
- **Head calibration protocol:**
  - 25 training dots + 9 held-out accuracy dots.
  - The user turns or moves their head until facing each dot, then holds still.
  - `HEAD_SETTLE_SECONDS = 0.55`, `HEAD_SAMPLE_SECONDS = 0.95`; about 45 s.
  - No stable/motion split and no pose-correction layer in head mode.
  - Filtering uses only the head/face dimensions; eye movement/blinks do not
    reject head samples.
  - Whole-face preview is shown; the eye crop and **EYES** label are used only
    in eye mode.
- **Model persistence:**
  - `MODEL_VERSION = 3`.
  - Saved JSON now contains both `control_mode` (`head`/`eyes`) and
    `model_mode` (`head6`/`iris8`).
  - `load()` resolves legacy files with only `model_mode: iris8` as eye mode,
    but version 2 and older files are rejected.
  - In head mode any saved pose-correction fields are ignored and forced off.
- **Runtime:**
  - `GazeEngine` skips the eye-openness gate in head mode.
  - Head mode uses a slightly faster 1€ filter (cutoff ×1.7, beta ×1.4) because
    head landmarks are less jittery than irises.
  - Status text is **Head tracking** or **Eye tracking**.
  - OSD and correction prompts say “head/facing” in head mode.
- **Mouse correction:** works in both modes; head mode captures the recent
  head features without requiring open eyes.
- **UI/docs:** settings header, Control row, calibration help, status labels,
  result screen, README, version `0.9.0`.

## Key Decisions

- **Head/face proxies instead of the MediaPipe 6-DOF transform.**
  The proxies are already normalized by interocular distance, are available
  even when `facial_transformation_matrixes` is absent, and are stable at
  30 fps. The transform is still available for a future model if the real data
  shows it maps better.
- **Keep eye mode.** It is cheap to retain and gives the user a fallback if
  head control does not feel right.
- **No pose correction in head mode.** The input already is head pose; a second
  correction would be redundant and harder to validate.
- **Head calibration should be fast.** Aim-and-hold needs no motion sub-window,
  so the total drops from ~80 s to ~45 s.
- **Old calibrations rejected.** Model version 3 and the mode check prevent a
  v0.7/v0.8 eye model from silently driving a head-control session.

## Evidence & Verification

| Check | Result |
| --- | --- |
| `pytest` | 42 passed |
| `ruff check .` | clean |
| `compileall eyelens` | clean |
| `python -m eyelens --smoke-test` | exit 0; reports old calibration needs recalibration |
| synthetic head calibration E2E through real `CalibrationWindow` | 34 points, `control_mode=head`, 0.0 px error, quality OK |
| synthetic head engine test | eyes closed (`openness=0`) still gives “Head tracking”; center 960,600 → moved 1632,960 when head features moved |
| head model unit tests | iris changes do not affect prediction; head changes do; save/load preserves mode and predictions |
| old mode load test | legacy `iris8` without `control_mode` resolves to eyes |

The synthetic E2E script lives outside the repo at
`C:\Users\avgrigorev\AppData\Local\Temp\opencode\head_calibration_e2e.py`.
It drives the actual calibration state machine with a fake tracker; it is not
part of the committed test suite.

## Real-Data Status

**No real head calibration has been run yet.** The algorithm is synthetic-tested
only. The next decisive step is the user’s real calibration:

1. Start eyeLens (`run.bat`). Settings should show **Control: Head**.
2. Click **Calibrate now**.
3. Aim the head at each dot — turn/move the head to face it, hold still.
4. Accept only if the measured error is ≤150 px; press Enter.
5. Test whether the lens follows the head, and whether it stays still while
   only the eyes move or blink.
6. Record `error_rmse`, whether the lens is usable, and any lag/overshoot.

The local `%LOCALAPPDATA%\eyeLens\calibration.json` is still an old rejected
eye/pose calibration. The first head calibration will overwrite it.

## Where We’re Going

1. **Real head calibration and acceptance test** (above). This is the
   decisive test of v0.9.
2. If head control works but feels too sensitive:
   - tune the global smoothing default or add a head-specific gain slider;
   - consider a small deadzone around the centre.
3. If the mapping quality is poor:
   - compare the six proxy features with MediaPipe’s raw 6-DOF pose features;
   - record per-point residuals before changing the model;
   - try a denser 6×6 head grid only if the error is a sampling problem.
4. Keep eye mode working; it shares the same model code but a different feature
   mask and calibration protocol.

## Risks & Blockers

- Real head data may be noisier or less linear than the synthetic mapping.
- The user must actually aim their head at the dots. Glancing with the eyes
  only produces a bad head calibration.
- Head control responds to posture changes. Sitting in a very different
  position after calibration moves the lens.
- Mode switching discards the in-memory model; only one calibration file is
  stored, so switching back may require recalibrating.
- `Modelfile` in the repo root remains an unrelated untracked file; leave it.

## Exact State

- Repo: `https://github.com/Closegamer/eyeLens` (private, `main`)
- Version: `0.9.0`
- Code commit: `3caf05b` — `feat: head-controlled lens with eye mode fallback (v0.9.0)`
- Tag: `v0.9.0`
- Virtualenv: `C:\a_REPOS\eyeLense\.venv` (Python 3.12)
- Tests: 42 passed; ruff clean; smoke exit 0
- Settings default: `control_mode="head"`; schema remains 2
- Old calibration file is rejected on load

## Quick Start for Next Session

```powershell
cd C:\a_REPOS\eyeLense
# Read continue_session.md, then this handoff.

.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m eyelens --smoke-test

run.bat
# Calibrate: aim your head at each dot and hold still (~45 s).
# Check the measured error and whether the lens follows your head.
# If it does not: record the error, try Smoothing, then inspect the mapping.
```

Key files:

- `eyelens/gaze/features.py` — control modes, feature masks, mode persistence.
- `eyelens/gaze/model.py` — head/eye feature selection, v3 save/load.
- `eyelens/ui/calibration_window.py` — head aiming protocol and texts.
- `eyelens/ui/settings_window.py` — Control combo and mode help.
- `eyelens/gaze/engine.py` — head-mode gating/filtering.
- `eyelens/app.py` — mode validation, calibration wiring, status copy.
