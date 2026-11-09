# eyeLens — Continue Session

**Memory:** `plans/handoffs/HANDOFF_eyelens-eye-preview_2026-11-09.md`
**Status:** v0.5.0 implemented, tested and pushed. Nothing running. Real-face
visual check and calibration accuracy are the pending tests.
**Repo:** `https://github.com/Closegamer/eyeLens` (private, branch `main`)
**Code commit:** `b967f9a` · tag `v0.5.0`
**Chain:** `standalone-08a28c4a` seq 5

## What changed in v0.5.0

- **Zoomed EYES panel during calibration**: a 320×150 close-up of both eyes,
  cropped from the camera around the eye/eyebrow band and upscaled to 640×300.
  Eye corners, lids, and iris centres are marked.
- **Small FACE inset** in the bottom-right of the EYES panel shows the whole
  camera frame for framing.
- The tracker has a new `eyes_preview_ready` signal; the calibration window
  falls back to the full preview if no face is detected.
- The calibration grid top moved down to ~230–240 px and the face status pill
  moved to y=184 so the larger preview does not overlap anything.
- Version `0.5.0`.

## What is next

1. Run `run.bat`, start calibration, and check the EYES panel: both eyes should
   fill it with aligned iris markers; the FACE inset should show framing.
2. If the crop is too tight/loose, adjust `span_x * 2.2` / `span_y * 1.8` in
   `eye_crop_box()` (`eyelens/gaze/tracker.py`).
3. If calibration is still not accurate enough, the next real step is
   **crop-based inference**: crop the face/eye region, run MediaPipe on it at a
   higher effective resolution, and map landmarks back. This needs a real-face
   test.
4. Real-face calibration and mouse-correction quality are still pending from
   v0.2/v0.3.

## Exact state

- Virtualenv: `C:\a_REPOS\eyeLense\.venv` (Python 3.12).
- Version: `0.5.0`.
- Tests: 29 passed; ruff clean; smoke test exit 0; synthetic calibration E2E
  still passes; offscreen EYES/FACE layout rendered correctly.
- `Modelfile` in the repo root is still an unrelated pre-existing file; leave it
  untracked.
- This memory file and the v0.5 handoff are committed in the session commit
  after `b967f9a`.
