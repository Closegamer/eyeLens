# eyeLens — mouse-drag local corrections (v0.3.0)

**Date:** 2026-11-09
**Status:** IMPLEMENTED — awaiting real-mouse / real-face test
**Bead(s):** none
**Epic:** none
**Chain:** `standalone-08a28c4a` seq `3`
**Parent:** `HANDOFF_eyelens-calibration-v2_2026-11-09.md`
**Prior code commit:** `7de4db4`, tag `v0.2.0`

---

## The Goal

The user asked:

> “we have to make trained model - when lens holds wrong position - user can
> take it with a mouse and put to right poritin so model will train this
> quickly”

So: when the lens is at the wrong place, let the user drag it with the mouse to
where they are actually looking, and make the model learn that correction
immediately.

## What Was Built

- **Correction mode** started by:
  - global hotkey `Ctrl + Alt + D`
  - tray menu **Correct lens position…**
  - settings window **Fix position** button
- **A small draggable handle** (`eyelens/ui/correction_handle.py`) appears at
  the lens centre:
  - separate 48×48 always-on-top tool window
  - the full-screen lens remains click-through, so only the handle captures the
    mouse; clicks anywhere else still reach the desktop
  - no-activate window, move cursor, four-arrow icon, right-click cancels
  - excluded from screen capture with `WDA_EXCLUDEFROMCAPTURE`
- **Drag flow**:
  1. The user presses the hotkey/button.
  2. The handle appears; the lens temporarily ignores gaze and follows the
     handle.
  3. The user drops the handle where they are looking.
  4. eyeLens keeps the lens at the drop point and asks the user to hold their
     gaze for 0.65 s.
  5. It takes the last 0.5 s of tracker history, keeps open-eye frames, removes
     per-feature outliers with MAD, and uses the median feature vector.
  6. It computes `target - base_prediction` and stores a local correction.
  7. The engine is recentered on the drop point so the lens does not jump away.
  8. The corrected model is saved to `calibration.json`.
- **Model update is not a full recalibration.** `GazeModel.with_correction`
  adds a correction centre to a local residual memory:
  - prediction = base polynomial/KRR prediction + weighted correction offset
  - RBF weights in standardized feature space (`gamma = 0.06`), squared and
    thresholded so the nearest correction dominates
  - a new correction removes nearby old centres (similarity ≥ 0.60) so
    repeated fixes replace rather than compound
  - at most 64 centres; O(corrections) work per frame, update is instant
  - correction offsets are stored relative to the base model and persisted as
    `{"features": [...], "offset": [dx, dy]}` under `corrections` in
    `calibration.json`
- **Tracker support** (`eyelens/gaze/tracker.py`):
  - thread-safe history deque of the last 120 snapshots
  - `recent_features(seconds, since)` returns a robust median feature vector
  - snapshot timestamps now use `time.monotonic()`, matching the app timers
- **Engine support**: `GazeEngine.recenter(x, y)` resets the 1€ filter at the
  corrected point; `set_model(..., reset=False)` avoids a filter reset when a
  correction is applied.
- **Safety/interaction details**:
  - correction requires a calibrated model, a ready camera, and no active
    calibration
  - correction is unavailable in demo mode
  - hiding the lens, starting calibration, changing camera, screen change, or
    quitting cancels correction mode
  - pressing `Ctrl+Alt+D` again cancels
  - if no face/open-eye frames are available, the correction is rejected with a
    message and the old model is kept
  - failure/cancel leaves the previous model intact
- Version bumped to `0.3.0`.

## Verification Done

| Check | Result |
| --- | --- |
| `ruff check .` | clean |
| `pytest` | 26 passed |
| `compileall` | clean |
| `python -m eyelens --smoke-test` | exit 0 |
| offscreen overlay correction flow | handle appears, drag moves lens, release emits target, hold/finish works |
| model correction unit test | 200 px error corrected to <2 px at the correction feature; same-region repeat replaces; save/load preserves |
| two distant corrections | both corrected to <0.1 px; no dilution |
| tracker history test | median of open frames; blinks/missing face rejected |

**Not verified:** actual Windows mouse drag of the handle and real-face
correction quality. The handle is a no-activate tool window; it is expected to
receive mouse events without activating the app, but this needs a real desktop
test.

## Key Decisions

- **Separate handle window, not a fully interactive lens.** Making the
  full-screen overlay accept mouse input would require custom hit-testing
  (`WM_NCHITTEST`) or would block clicks everywhere. A small separate window
  keeps the lens click-through and the desktop usable.
- **Local residual memory, not a refit.** The user asked for “train this
  quickly”. A full `GazeModel.fit` takes 1–2 s and reruns grouped CV. Storing a
  local correction centre is instantaneous, applies exactly at the corrected
  gaze features, decays elsewhere, and is easy to persist.
- **Hold-then-capture.** Capturing immediately on mouse release mixes drag
  frames with the final gaze. A 0.65 s hold then a 0.5 s window gives clean
  post-release features.
- **Median + MAD.** The tracker history is filtered for open eyes and
  per-feature outliers, then medianed; one bad landmark frame cannot poison the
  correction.
- **Replace nearby corrections.** A second drag in the same region should
  supersede the first, not sum to an overshoot.
- **Squared RBF weights with a threshold.** Prevents many unrelated corrections
  from diluting the nearest one.

## Files Changed

- `eyelens/ui/correction_handle.py` — new draggable handle window.
- `eyelens/ui/overlay.py` — correction mode, handle wiring, drop target, hold.
- `eyelens/gaze/model.py` — `with_correction`, correction layer, persistence.
- `eyelens/gaze/tracker.py` — snapshot history + `recent_features`.
- `eyelens/gaze/engine.py` — `recenter`, optional filter reset.
- `eyelens/app.py` — hotkey/tray/settings wiring, hold timer, learn/save flow.
- `eyelens/hotkeys.py` — `Ctrl+Alt+D`.
- `eyelens/ui/settings_window.py` — Fix position button, hotkey row, help text.
- `README.md` — feature, controls, how-it-works, troubleshooting.
- `tests/test_model.py` — correction/replacement/persistence test.
- `tests/test_tracker.py` — recent-feature filtering test.
- `pyproject.toml`, `eyelens/__init__.py` — version 0.3.0.

## Where We're Going

1. **Real desktop test**: run `run.bat`, calibrate, press `Ctrl+Alt+D`, confirm
   the handle receives mouse drags, drop it, and check that the lens stays near
   the corrected spot afterward.
2. If the handle does not receive clicks, inspect the Windows exstyles
   (`WS_EX_NOACTIVATE`, tool window) and consider removing `WS_EX_NOACTIVATE`
   for the handle only.
3. If one correction is not strong enough, the user can repeat in the same
   spot; if it is too broad, lower `_CORRECTION_GAMMA` / raise it as needed.
4. If corrections feel good, consider showing a tiny “correction learned” tick
   or a list/reset of corrections in the settings window.
5. Continue the roadmap: camera pause/privacy toggle, multi-monitor, packaging.

## Quick Start for Next Session

```powershell
cd C:\a_REPOS\eyeLense
# Read: continue_session.md, then this handoff
# Repo: https://github.com/Closegamer/eyeLens (private)
# Branch: main, commit 9500bd7, tag v0.3.0

.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m eyelens --smoke-test

# Real product
run.bat
# Then: calibrate, press Ctrl+Alt+D, drag the handle, release, hold gaze 0.65 s.

# Key files
#   eyelens/ui/correction_handle.py
#   eyelens/ui/overlay.py
#   eyelens/gaze/model.py  (with_correction, _correction_offset)
#   eyelens/gaze/tracker.py (recent_features)
#   eyelens/app.py (correct_lens, _learn_correction)
```

## Session Closed

**Closed at:** 2026-11-09
**Commit:** `9500bd7` pushed to `origin/main`; tag `v0.3.0` pushed.
Follow-up `632cd1e` on `main` tightens the correction replacement radius and
guards handle teardown.
**Status:** Implemented and synthetically verified. Real mouse drag and
real-face correction quality remain the acceptance tests.
