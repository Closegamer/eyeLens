# Next Session Bootstrap

Read `plans/handoffs/HANDOFF_eyelens-mvp_2026-11-09.md` (seq 1,
`standalone-08a28c4a`) and continue from **Where We're Going**.

## State

- eyeLens MVP is complete, tested, committed as `44701b0`, tagged `v0.1.0` and
  pushed to the private repo `Closegamer/eyeLens`.
- Nothing is running. The previous session ended with a computer shutdown at the
  user's request.
- The main unverified item is a real-person calibration: the automated camera
  test had no face in view, so only synthetic calibration and UI checks passed.

## First actions

1. Read `continue_session.md`, then the handoff.
2. Verify the toolchain:
   `.\.venv\Scripts\python.exe -m pytest -q`
   `.\.venv\Scripts\ruff.exe check .`
3. Launch `run.bat`, keep a face visible in camera 0, and complete the 25-point
   calibration.
4. Record measured accuracy and adjust only if needed.

## Do not

- Do not ask the user to paste handoff text; read the memory files.
- Do not commit the unrelated root `Modelfile`.
- Do not start long-running jobs automatically; none are pending.
