# eyeLens — Continue Session

**Memory:** `plans/handoffs/HANDOFF_eyelens-head-control_2026-11-12.md`
**Status:** v0.11.0 implemented, tested, tagged. **Real head calibration and
wheel-trim acceptance tests pending.**
**Repo:** `https://github.com/Closegamer/eyeLens` (private, branch `main`)
**Code commits:** `5a24534` (head control), `882fed9` (pointer fallback),
`7225e20` (interactive lens + edge reach), `72f00b3` (wheel fine trim)
**History:** author/committer email rewritten to `closegamer@mail.ru` on
2026-11-12; commit hashes changed and the branch was force-pushed.
**Tags:** `v0.9.0`, `v0.9.1`, `v0.10.0`, `v0.11.0`
**Chain:** `standalone-08a28c4a` seq 9

## What changed in v0.11.0

- **Ctrl+Alt+Wheel = manual lens fine trim.**
  - A global `pynput` mouse listener plus `GetAsyncKeyState` detects Ctrl+Alt
    while scrolling. Works while another app has focus.
  - Wheel up moves the lens up (`trim_y -= 10`), wheel down moves it down;
    horizontal wheel moves left/right. Step = 10 logical px.
  - Trim is stored in `Settings.trim_x` / `trim_y`, clamped to ±1200 px, saved
    with the settings, and survives restarts.
  - Only camera-driven modes use it; pointer/demo mode is unchanged.
  - `Ctrl+Alt+0` or **Reset trim** in Settings clears it; a new calibration
    also resets it.
  - The OSD shows the current trim after each notch; the status detail shows it
    when nonzero.
  - Wheel over the lens with Ctrl+Alt held is swallowed by the overlay so the
    app underneath does not also scroll.
  - Mouse-drag corrections now subtract the trim before learning the model
    correction, so the dropped lens stays exactly where the user released it.
- Version `0.11.0`.

## What is next

1. Restart eyeLens (`run.bat`) and load/calibrate head control.
2. Look at the top of the screen; if the lens sits lower, hold **Ctrl+Alt** and
   scroll **up** until the lens reaches the area you are looking at. Scroll
   down/sideways as needed. Each notch = 10 px.
3. Press `Ctrl+Alt+0` (or Settings → **Reset trim**) to clear the trim and
   confirm the lens returns to its untrimmed position.
4. Test the trim in eye mode too, and check it survives an app restart.
5. Test clicking/edge reach from v0.10.0 and pointer fallback from v0.9.1.
6. Record whether 10 px per notch is fine enough or too slow; adjust
   `Settings.TRIM_STEP` if needed.

## Exact state

- Virtualenv: `C:\a_REPOS\eyeLense\.venv` (Python 3.12).
- Version: `0.11.0`.
- Tests: 48 passed; ruff clean; compileall clean; smoke test exit 0.
- Global wheel listener verified: wheel up/down emitted `(0, 1)` / `(0, -1)`.
- Engine trim test: prediction 500,400 + trim (40,-30) → lens (540,370).
- Native overlay tests from v0.10: mapped click and wheel reached the target.
- `%LOCALAPPDATA%\eyeLens\calibration.json` is still an old rejected
  eye/pose calibration; the first head calibration overwrites it.
- `Modelfile` in the repo root is an unrelated pre-existing untracked file;
  leave it untracked.

## Known limitations

- Ctrl+Alt+wheel is global; apps that also react to it may scroll while the
  lens trims. The overlay itself swallows it.
- Trim is a global screen-space offset, not a per-region correction; use
  `Ctrl+Alt+D` for local errors.
- Dragging inside the lens is not remapped; clicks, double-clicks, right-clicks
  and wheel are.
- Synthetic clicks may be rejected by elevated apps.
