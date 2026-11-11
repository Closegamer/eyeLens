# eyeLens — Continue Session

**Memory:** `plans/handoffs/HANDOFF_eyelens-head-control_2026-11-12.md`
**Status:** v0.9.0 implemented, tested, tagged. **Real head calibration pending.**
**Repo:** `https://github.com/Closegamer/eyeLens` (private, branch `main`)
**Code commit:** `3caf05b` · tag `v0.9.0`
**Chain:** `standalone-08a28c4a` seq 9

## What changed in v0.9.0

- **The lens is now controlled by the head, not the eyes.** Head control is the
  default. It fits only the six gaze-independent head/face features, so moving
  your eyes, blinking, or closing your eyes does not move or freeze the lens.
- **Eye control is still available** in Settings → **Control**. Each mode needs
  its own calibration; switching mode invalidates the current one.
- **Head calibration is aim-and-hold:** turn or move your head to face each of
  the 25 dots, then hold still. 9 held-out accuracy dots follow. About 45 s.
  There is no stable/motion split and no head-pose correction in head mode.
- **Model version 3** saves `control_mode` (`head`/`eyes`) and `model_mode`
  (`head6`/`iris8`). Old v0.7/v0.8 calibrations are rejected.
- Runtime status says **Head tracking**; the eye-openness gate is skipped in
  head mode and the 1€ filter is slightly faster.
- UI copy, calibration previews, result screen, mouse correction prompts,
  README and version (`0.9.0`) were updated.

## What is next

1. Start eyeLens (`run.bat`). Settings should show **Control: Head**.
2. Click **Calibrate now**.
3. For each dot, turn or move your head until you are facing it, then hold
   still while the ring fills. Do not just glance with your eyes.
4. The result must be “Good” (≤150 px) to accept; press Enter. Record the
   measured error.
5. Check that the lens follows your head and stays put while only your eyes
   move or while you blink.
6. Use `Ctrl+Alt+D` to drag the lens to any off spot; the head model learns it.
7. If head control feels too sensitive or laggy, adjust **Smoothing** and report
   the direction. If accuracy is poor, record the px error and per-region
   behaviour before changing the model.

## Exact state

- Virtualenv: `C:\a_REPOS\eyeLense\.venv` (Python 3.12).
- Version: `0.9.0`.
- Tests: 42 passed; ruff clean; compileall clean; smoke test exit 0.
- Synthetic head calibration E2E (real `CalibrationWindow` state machine,
  fake tracker): 34 points, 0.0 px error, quality OK.
- Synthetic head engine test: eyes closed still gives “Head tracking”; head
  movement moves the lens in the expected direction.
- `%LOCALAPPDATA%\eyeLens\calibration.json` is still an old rejected
  eye/pose calibration; the first head calibration overwrites it.
- `Modelfile` in the repo root is an unrelated pre-existing untracked file;
  leave it untracked.
- No real-face head calibration has been run yet. That is the next decisive
  test.
