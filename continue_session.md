# eyeLens — Continue Session

**Memory:** `plans/handoffs/HANDOFF_eyelens-mouse-correction_2026-11-09.md`
**Status:** v0.3.0 implemented, tested and pushed. Nothing running. Real-mouse and
real-face correction quality are the first pending tests.
**Repo:** `https://github.com/Closegamer/eyeLens` (private, branch `main`)
**Code commit:** `9500bd7` · follow-up `632cd1e` · tag `v0.3.0`
**Chain:** `standalone-08a28c4a` seq 3

## What changed in v0.3.0

- **Mouse correction**: press `Ctrl+Alt+D` (or tray **Correct lens position…**,
  or settings **Fix position**). A small draggable handle appears at the lens
  centre. Drag it to where you are actually looking and release. The lens holds
  that spot for 0.65 s, captures a robust recent feature vector, stores a local
  residual correction, recenters the engine, and saves the calibration.
- The full-screen lens stays click-through; only the 48×48 handle captures the
  mouse, so the rest of the desktop remains usable.
- The correction is an RBF-weighted local memory on top of the fitted model, not
  a full recalibration. It applies where the user corrected, decays elsewhere,
  replaces nearby older corrections, is capped at 64 centres, and is persisted
  in `calibration.json`.
- Tracker history (`recent_features`) supplies a median open-eye feature vector
  from the hold window.
- Version `0.3.0`.

## What is next

1. Run `run.bat`, calibrate, then press `Ctrl+Alt+D`, drag the handle, release,
   and hold your gaze on the lens. Confirm the lens stays corrected afterward.
2. If the handle does not receive mouse drags on Windows, inspect the handle
   exstyles (`WS_EX_NOACTIVATE`, tool window). The handle is expected to receive
   clicks without activating.
3. Tune `_CORRECTION_GAMMA` / `_CORRECTION_SIMILARITY` in
   `eyelens/gaze/model.py` if corrections feel too broad/narrow or replace too
   aggressively.
4. The earlier v0.2 calibration work still needs a real-face accuracy test;
   read `HANDOFF_eyelens-calibration-v2_2026-11-09.md` for the model details.

## Exact state

- Virtualenv: `C:\a_REPOS\eyeLense\.venv` (Python 3.12).
- Version: `0.3.0`.
- Tests: 26 passed; ruff clean; smoke test exit 0.
- `Modelfile` in the repo root is still an unrelated pre-existing file; leave it
  untracked.
- This memory file and the v0.3 handoff are committed in the session commit
  after `9500bd7`.
