# eyeLens — Continue Session

**Memory:** `plans/handoffs/HANDOFF_eyelens-mvp_2026-11-09.md`
**Status:** MVP complete and pushed. Nothing is running. No long jobs to resume.
**Repo:** `https://github.com/Closegamer/eyeLens` (private, branch `main`)
**Code commit:** `44701b0` · tag `v0.1.0`
**Chain:** `standalone-08a28c4a` seq 1

## What is done

- PySide6 click-through always-on-top magnifying lens (120–600 px, 1×–6×,
  opacity, HUD, freeze, tray, global hotkeys).
- MediaPipe webcam tracking, 25-point calibration, ridge gaze model, 1€
  smoothing, blink/loss handling, settings persistence.
- WDA `0x11` capture exclusion so the lens never films itself.
- Demo mode (`python -m eyelens --demo`), docs, screenshots, 18 tests, ruff and
  CI. Final gates pass.

## What is next

1. Run `run.bat` and complete a real-face 25-point calibration using camera 0.
2. Measure actual accuracy and subjective feel; tune features/grid if needed.
3. Then consider camera pause, multi-monitor, packaging and lens shapes.

## Exact state

- Virtualenv: `C:\a_REPOS\eyeLense\.venv` (Python 3.12).
- Settings: `%LOCALAPPDATA%\eyeLens\settings.json` (defaults).
- Calibration: not created yet; a real calibration is the first pending step.
- `Modelfile` in the repo root is an unrelated pre-existing file; leave it
  untracked. Only the handoff/session commit is untracked otherwise.

Read the full handoff before changing code. It contains benchmarks, rejected
approaches, thresholds, file map and the validation checklist.
