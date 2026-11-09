# eyeLens — zoomed eye preview during calibration (v0.5.0)

**Date:** 2026-11-09
**Status:** IMPLEMENTED — awaiting real-face visual check
**Bead(s):** none
**Epic:** none
**Chain:** `standalone-08a28c4a` seq `5`
**Parent:** `HANDOFF_eyelens-shapes-big-lens_2026-11-09.md`
**Prior code commit:** `d0d9454`, tag `v0.4.0`

---

## The Goal

The user asked:

> “make eyes of user zoomed much when calibrating - we need more accurate
> positioning.”

So: during calibration, show a much larger, zoomed view of the user's eyes so
they can position their face and verify iris tracking precisely.

## What Was Built

- **Tracker eye preview** (`eyelens/gaze/tracker.py`):
  - new `eyes_preview_ready(QImage)` signal, emitted alongside the existing
    whole-face `preview_ready`
  - `eye_crop_box()` computes a fixed-aspect (640×300) crop centred on the eye
    and eyebrow landmarks, clamped to the camera frame
  - the crop is upscaled with bicubic interpolation and the eye corners,
    upper/lower lids, and iris centres are marked
  - the full preview still exists for the settings window and the FACE inset
- **Calibration UI** (`eyelens/ui/calibration_window.py`):
  - large **EYES** panel (320×150) at the top-left, showing the zoomed eye crop
  - small **FACE** inset (88×50) in the bottom-right of the panel, showing the
    whole camera frame for framing
  - when no face is detected, the panel falls back to the full camera preview
    and the label changes from EYES to CAMERA
  - the face status pill moved to y=184; the calibration grid top moved from
    ~195 to ~230–240 px so the larger preview does not overlap the dots
  - `PREVIEW_RECT` / `FACE_PILL_RECT` class constants keep the layout
    consistent
- **App wiring**: connects/disconnects `eyes_preview_ready` when the
  calibration window opens/closes.
- **Docs/tests**: README describes the EYES/FACE panels; `test_tracker.py`
  covers the crop box and QImage emission; version 0.5.0.

## Verification Done

| Check | Result |
| --- | --- |
| `ruff check .` | clean |
| `pytest` | 29 passed |
| `compileall` | clean |
| `python -m eyelens --smoke-test` | exit 0 |
| synthetic tracker preview | full 480×270 and eye 640×300 emitted; eye crop shows both eyes |
| offscreen calibration layout | 320×150 EYES panel, FACE inset, face pill, and top dots do not overlap |
| synthetic calibration E2E | still reaches RESULT with 34 points |

**Not verified:** real camera eye-crop appearance and real-face calibration
accuracy. The preview is a visual aid; it does not change the landmark
inference. If the user expects the model to see more detail, the next step is a
two-stage crop-based inference pass (crop the face/eye region, run the landmarker
on the crop, map landmarks back).

## Key Decisions

- **Eye-band crop, not a larger whole-face panel.** The current whole-face
  preview makes each eye tiny. Cropping the eye/eyebrow band fills the panel
  with the eyes and the marked iris centres.
- **Fixed 640×300 / 320×150 aspect.** The crop box is built to that aspect, so
  the panel never stretches the image.
- **FACE inset.** The zoomed view loses framing context; a small whole-frame
  inset keeps it visible without covering the eyes (placed bottom-right).
- **Grid moved down.** The preview grew from 208×117 to 320×150; the face pill
  and top calibration row moved down to avoid overlap.
- **Preview only.** No extra inference pass was added; that would be a larger,
  riskier change requiring a real-face test.

## Files Changed

- `eyelens/gaze/tracker.py` — eye crop helper, eye preview signal/emission.
- `eyelens/ui/calibration_window.py` — EYES panel, FACE inset, layout shift.
- `eyelens/app.py` — connect/disconnect eye preview.
- `README.md` — EYES/FACE preview and troubleshooting.
- `tests/test_tracker.py` — crop-box and preview-emission tests.
- `pyproject.toml`, `eyelens/__init__.py` — version 0.5.0.

## Where We're Going

1. Run `run.bat`, calibrate, and check the EYES panel: both eyes should fill the
   panel with aligned iris markers and the FACE inset should show framing.
2. If the eye crop feels too tight/loose, adjust `span_x * 2.2` / `span_y * 1.8`
   in `eye_crop_box()`.
3. If calibration accuracy is still poor, implement the next real step:
   crop the face/eye region and run MediaPipe at a higher effective resolution,
   then map the landmarks back. This needs a real-face test.
4. Real-face calibration and mouse-correction quality remain the main pending
   acceptance tests from v0.2/v0.3.

## Quick Start for Next Session

```powershell
cd C:\a_REPOS\eyeLense
# Read: continue_session.md, then this handoff
# Repo: https://github.com/Closegamer/eyeLens (private)
# Branch: main, commit b967f9a, tag v0.5.0

.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m eyelens --smoke-test

# Real product
run.bat
# Calibrate and inspect the large EYES panel + small FACE inset.
```

## Session Closed

**Closed at:** 2026-11-09
**Commit:** `b967f9a` pushed to `origin/main`; tag `v0.5.0` pushed.
**Status:** Implemented and synthetically verified. Real-face visual check
remains.
