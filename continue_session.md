# eyeLens — Continue Session

**Memory:** `plans/handoffs/HANDOFF_eyelens-head-pose_2026-11-09.md`
**Status:** v0.7.0 implemented, tested and pushed. Nothing running. A fresh
real-face recalibration is required to collect head pose and enable the pose
correction.
**Repo:** `https://github.com/Closegamer/eyeLens` (private, branch `main`)
**Code commit:** `3586510` · tag `v0.7.0`
**Chain:** `standalone-08a28c4a` seq 7

## What changed in v0.7.0

- MediaPipe now outputs the **6-DOF facial transformation matrix**. The tracker
  extracts the face forward vector and head translation with every frame.
- Calibration records head pose per sample. After the 9 validation points, a
  global ridge **head-pose correction** is fitted on the primary residuals.
- The correction is enabled only if it improves the held-out validation by at
  least **3% and 5 px**; otherwise it is off and the eye-only model is used.
- At runtime the pose correction changes with head position, recalculating the
  mapping as the head moves.
- New calibration files store `pose_samples`/`pose_alpha`/`pose_weight`; the
  summary shows **head pose** when active.
- Old calibrations without pose still load eye-only. **Recalibrate once** to
  collect pose.
- Version `0.7.0`.

## What is next

1. Restart eyeLens, recalibrate once, keep the head still during calibration.
2. Check the result summary for **head pose**.
3. Test moving the head slightly while looking at the same screen point.
4. If pose correction is not selected but head movement still hurts, the next
   step is a proper 3D gaze/head model (eye position + gaze ray intersection
   with the screen plane), not a linear residual.
5. If selected, tune `POSE_ALPHAS` / the 3%+5 px threshold.
6. Denser grid and crop-based eye landmark inference remain options for the
   base ~90–100 px error floor.

## Exact state

- Virtualenv: `C:\a_REPOS\eyeLense\.venv` (Python 3.12).
- Version: `0.7.0`.
- Tests: 34 passed; ruff clean; smoke test exit 0; synthetic pose calibration E2E
  passes; pose save/load test passes.
- `Modelfile` in the repo root is still an unrelated pre-existing file; leave it
  untracked.
- This memory file and the v0.7 handoff are committed in the session commit
  after `3586510`.
