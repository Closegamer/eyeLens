# eyeLens — Continue Session

**Memory:** `plans/handoffs/HANDOFF_eyelens-stable-motion_2026-11-10.md`
**Status:** v0.8.0 implemented, tested and pushed. The previous calibration was
rejected; a fresh stable+motion recalibration is required.
**Repo:** `https://github.com/Closegamer/eyeLens` (private, branch `main`)
**Code commit:** `302e6b2` · tag `v0.8.0`
**Chain:** `standalone-08a28c4a` seq 8

## What changed in v0.8.0

- **Real data showed the shuffled dot order was harmful**: several dots were
  mislooked, validation error 262 px. The predictable **centre-out** order is
  restored and settle time is 0.65 s.
- **Each dot now has a stable part and a head-movement part**:
  - first 0.65 s: hold still; frames train the base eye-only model;
  - next 1.0 s: keep eyes on the dot and slowly move your head left/right;
    frames train the head-pose correction.
- The pose correction is fitted on motion frames (same target, varied pose),
  stored as reusable coefficients, and enabled only if the combined stable+motion
  validation improves by ≥5% and ≥10 px.
- **Quality gate**: the result screen refuses Enter/Space unless the measured
  error is ≤150 px; press R to retry. Bad calibrations cannot be saved.
- The old v0.7 pose calibration has no usable motion correction record and is
  **rejected**; eyeLens will ask for recalibration.
- Calibration now takes about **80 seconds**. The active dot is larger/brighter.
- Version `0.8.0`.

## What is next

1. Restart eyeLens (old calibration rejected), click **Calibrate**.
2. For each dot: hold still first, then keep eyes on the dot and move your head
   slowly left/right for the motion part.
3. The result must be “Good” (≤150 px) to accept. Check whether the summary says
   **head pose**.
4. If still >150 px, try again; if repeated, next options: denser 6×6 grid,
   explicit left-right/up-down motion, or a proper 3D gaze/head model.
5. Real-face calibration and mouse-correction quality remain the acceptance
   tests.

## Exact state

- Virtualenv: `C:\a_REPOS\eyeLense\.venv` (Python 3.12).
- Version: `0.8.0`.
- Tests: 34 passed; ruff clean; smoke test exit 0; synthetic calibration E2E
  passes; synthetic pose-correction and save/load tests pass; old v0.7
  calibration load is rejected.
- `Modelfile` in the repo root is still an unrelated pre-existing file; leave it
  untracked.
- This `continue_session.md` and the formal v0.8 handoff are committed together
  in the session handoff commit. The next session should read
  `continue_session.md` first, then the handoff, and start with the stable+motion
  recalibration.
