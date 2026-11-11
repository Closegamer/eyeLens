# eyeLens — Continue Session

**Memory:** `plans/handoffs/HANDOFF_eyelens-head-control_2026-11-12.md`
**Status:** v0.9.1 implemented, tested, tagged. **Real head calibration pending.**
**Repo:** `https://github.com/Closegamer/eyeLens` (private, branch `main`)
**Code commits:** `3caf05b` (v0.9.0 head control), `c1506c0` (v0.9.1 pointer fallback)
**Tags:** `v0.9.0`, `v0.9.1`
**Chain:** `standalone-08a28c4a` seq 9

## What changed in v0.9.x

- **The lens is head-controlled by default, not eye-controlled.** Head mode fits
  only the six gaze-independent head/face features, so moving your eyes,
  blinking, or closing your eyes does not move or freeze the lens.
- **Eye control remains available** in Settings → **Control** as a fallback.
  Each mode has its own calibration; switching mode asks for recalibration.
- **Head calibration is aim-and-hold:** turn or move your head to face each of
  the 25 dots, then hold still. 9 held-out accuracy dots follow. About 45 s.
  There is no stable/motion split and no head-pose correction in head mode.
- **Automatic mouse / touch fallback (v0.9.1):** if the camera or face model is
  unavailable, the lens switches to pointer mode on its own. It follows the
  mouse or a finger on a touchscreen (Windows maps touch to pointer movement).
  No calibration is needed in this mode.
  - The app watches camera startup for 7 s and also reacts to tracker errors.
  - Pointer mode shows **Mouse / touch** in the status and keeps all lens
    controls (show/hide, freeze, zoom, size, big lens) usable.
  - When the camera becomes ready again, head tracking resumes if a matching
    calibration exists. Otherwise pointer mode stays until you calibrate.
  - Settings → **Apply** retries the camera after freeing it.
- **Model version 3** saves `control_mode` (`head`/`eyes`) and `model_mode`
  (`head6`/`iris8`). Old v0.7/v0.8 calibrations are rejected.
- Runtime status says **Head tracking**; the eye-openness gate is skipped in
  head mode and the 1€ filter is slightly faster.
- UI copy, calibration previews, result screen, mouse correction prompts,
  README and version (`0.9.1`) were updated.

## What is next

1. Start eyeLens (`run.bat`). Settings should show **Control: Head**.
2. Click **Calibrate now**.
3. For each dot, turn or move your head until you are facing it, then hold
   still while the ring fills. Do not just glance with your eyes.
4. The result must be “Good” (≤150 px) to accept; press Enter. Record the
   measured error.
5. Check that the lens follows your head and stays put while only your eyes
   move or while you blink.
6. Test the no-camera path too: disable/unplug the camera (or close the app
   using it), start eyeLens, and confirm **Mouse / touch** appears and the lens
   follows the mouse or a finger. Then restore the camera and press **Apply**.
7. If head control feels too sensitive or laggy, adjust **Smoothing** and report
   the direction. If accuracy is poor, record the px error and per-region
   behaviour before changing the model.

## Exact state

- Virtualenv: `C:\a_REPOS\eyeLense\.venv` (Python 3.12).
- Version: `0.9.1`.
- Tests: 44 passed; ruff clean; compileall clean; smoke test exit 0.
- Synthetic head calibration E2E (real `CalibrationWindow` state machine,
  fake tracker): 34 points, 0.0 px error, quality OK.
- Synthetic head engine test: eyes closed still gives “Head tracking”; head
  movement moves the lens in the expected direction.
- Missing-model app test (offscreen, real `EyeLensApp`): pointer fallback
  activates, engine reports “Mouse / touch”, overlay becomes visible.
- `%LOCALAPPDATA%\eyeLens\calibration.json` is still an old rejected
  eye/pose calibration; the first head calibration overwrites it.
- `Modelfile` in the repo root is an unrelated pre-existing untracked file;
  leave it untracked.
- No real-face head calibration has been run yet. That is the next decisive
  test.
