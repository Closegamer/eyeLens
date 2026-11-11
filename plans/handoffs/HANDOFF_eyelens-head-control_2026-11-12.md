# eyeLens — head control, pointer fallback, interactive lens, wheel trim (v0.11.0)

**Date:** 2026-11-12
**Status:** IMPLEMENTED — real head calibration pending
**Chain:** `standalone-08a28c4a` seq `9`
**Parent:** `HANDOFF_eyelens-stable-motion_2026-11-10.md`
**Prior chain:** `HANDOFF_eyelens-mvp_2026-11-09.md` > `HANDOFF_eyelens-calibration-v2_2026-11-09.md` > `HANDOFF_eyelens-mouse-correction_2026-11-09.md` > `HANDOFF_eyelens-shapes-big-lens_2026-11-09.md` > `HANDOFF_eyelens-eye-preview_2026-11-09.md` > `HANDOFF_eyelens-eye-only-model_2026-11-09.md` > `HANDOFF_eyelens-head-pose_2026-11-09.md` > `HANDOFF_eyelens-stable-motion_2026-11-10.md` > this

---

## Request

> “make lense control by the head but not by eyes - then we will have more control on it”

The user asked for a decisive pivot away from iris gaze.  Head control is now
the default.  Eye control is retained only as an optional fallback in Settings.

## What Changed

- **Head control is the default.**
  - `GazeModel.control_mode == "head"` fits only the six gaze-independent
    head/face features: `head_yaw`, `head_pitch`, `head_roll`, `face_x`,
    `face_y`, `face_size` (feature indices 8–13).
  - Iris features are zeroed before fitting and prediction.  Looking around,
    blinking, or closing the eyes does not move or freeze the lens.
- **Eye control remains available.**
  - Settings → **Control** offers **Head** (default) and **Eyes**.
  - Eye mode still uses the eight iris features and the v0.8 stable+motion
    protocol.
  - Switching mode invalidates the current calibration, hides the lens, and
    asks for recalibration in the new mode.
- **Head calibration protocol:**
  - 25 training dots + 9 held-out accuracy dots.
  - The user turns or moves their head until facing each dot, then holds still.
  - `HEAD_SETTLE_SECONDS = 0.55`, `HEAD_SAMPLE_SECONDS = 0.95`; about 45 s.
  - No stable/motion split and no pose-correction layer in head mode.
  - Filtering uses only the head/face dimensions; eye movement/blinks do not
    reject head samples.
  - Whole-face preview is shown; the eye crop and **EYES** label are used only
    in eye mode.
- **Model persistence:**
  - `MODEL_VERSION = 3`.
  - Saved JSON now contains both `control_mode` (`head`/`eyes`) and
    `model_mode` (`head6`/`iris8`).
  - `load()` resolves legacy files with only `model_mode: iris8` as eye mode,
    but version 2 and older files are rejected.
  - In head mode any saved pose-correction fields are ignored and forced off.
- **Runtime:**
  - `GazeEngine` skips the eye-openness gate in head mode.
  - Head mode uses a slightly faster 1€ filter (cutoff ×1.7, beta ×1.4) because
    head landmarks are less jittery than irises.
  - Status text is **Head tracking** or **Eye tracking**.
  - OSD and correction prompts say “head/facing” in head mode.
- **Mouse correction:** works in both modes; head mode captures the recent
  head features without requiring open eyes.
- **Mouse / touch pointer fallback (v0.9.1):**
  - When the tracker reports an error (no camera, camera busy, missing face
    model) or is still not ready after 7 seconds, the app enters pointer mode.
  - `GazeEngine.set_pointer_fallback(True)` follows `QCursor.pos()` at 60 Hz;
    no model or calibration is required. Windows maps touchscreen input to
    pointer movement, so a finger works like the mouse.
  - The lens overlay treats pointer mode as available; show/hide, freeze,
    zoom, size, and big-lens controls all keep working. Correction is disabled
    because pointer control is already exact.
  - `EyeLensApp` shows **Mouse / touch** in the status, sets `lens_visible`,
    and tells the user to press **Apply** to retry the camera.
  - If the camera becomes ready and a matching calibration exists, the app
    automatically leaves pointer mode and resumes camera tracking. Without a
    calibration it stays in pointer mode so the lens remains usable.
- **Interactive lens clicks (v0.10.0):**
  - The overlay is no longer fully `WS_EX_TRANSPARENT`.  `nativeEvent`
    handles `WM_NCHITTEST`: HTCLIENT inside the current lens shape,
    HTTRANSPARENT everywhere else.  Clicks outside still reach the desktop.
  - `mousePressEvent` records the mapped source point and defers the real
    click until `mouseReleaseEvent`.  Injecting while the physical button is
    down makes Windows route the synthetic click back to the overlay.
  - `_inject_click` sets `_force_click_through`, warps the cursor to the
    source point, sends `mouse_event` down/up, restores the cursor, and keeps
    click-through for 60 ms while input is delivered.
  - Left, right and middle buttons, double-clicks, vertical and horizontal
    wheel are forwarded.  Drags are not remapped yet.
  - `WM_NCHITTEST` coordinates are physical pixels; they are divided by the
    screen device pixel ratio before the logical lens hit-test.
- **Edge-to-edge lens (v0.10.0):**
  - `clamp_lens_center` allows the lens centre anywhere from `0` to the screen
    width/height.  The lens is partially clipped at the border by design.
  - This makes the taskbar and corners reachable; previously the lens stopped
    half a diameter inside the screen.
  - Head calibration uses near-border targets:
    x = 0.03/0.265/0.5/0.735/0.97, y = 0.10..0.96, so the head model can
    predict the taskbar.  Eye mode keeps the conservative interior grid.
- **Ctrl+Alt+wheel fine trim (v0.11.0):**
  - `HotkeyManager` now owns a global `pynput.mouse.Listener`; `_on_scroll`
    checks `GetAsyncKeyState(VK_CONTROL/VK_MENU)` and emits `trim_lens(dx, dy)`.
  - `EyeLensApp._on_trim_lens` adds `dx * 10` and subtracts `dy * 10` from
    `Settings.trim_x/trim_y` (screen y grows downwards), clamped to ±1200.
  - Trim is persisted in settings, shown in the OSD and status detail, applied
    only to camera-driven predictions in `GazeEngine.poll`, ignored in
    pointer/demo mode.
  - `Ctrl+Alt+0` and Settings → **Reset trim** clear it; a successful
    calibration resets it.
  - The overlay swallows Ctrl+Alt+wheel over the lens so the app underneath
    does not scroll twice.
  - Mouse-drag correction subtracts the trim from its target, so the lens stays
    at the dropped point after the model learns the local correction.
- **UI/docs:** settings header, Control row, calibration help, status labels,
  result screen, hotkey list, README, version `0.11.0`.

## Key Decisions

- **Head/face proxies instead of the MediaPipe 6-DOF transform.**
  The proxies are already normalized by interocular distance, are available
  even when `facial_transformation_matrixes` is absent, and are stable at
  30 fps. The transform is still available for a future model if the real data
  shows it maps better.
- **Keep eye mode.** It is cheap to retain and gives the user a fallback if
  head control does not feel right.
- **No pose correction in head mode.** The input already is head pose; a second
  correction would be redundant and harder to validate.
- **Head calibration should be fast.** Aim-and-hold needs no motion sub-window,
  so the total drops from ~80 s to ~45 s.
- **Old calibrations rejected.** Model version 3 and the mode check prevent a
  v0.7/v0.8 eye model from silently driving a head-control session.

## Evidence & Verification

| Check | Result |
| --- | --- |
| `pytest` | 48 passed |
| `ruff check .` | clean |
| `compileall eyelens` | clean |
| `python -m eyelens --smoke-test` | exit 0; reports old calibration needs recalibration |
| synthetic head calibration E2E through real `CalibrationWindow` | 34 points, `control_mode=head`, 0.0 px error, quality OK |
| synthetic head engine test | eyes closed (`openness=0`) still gives “Head tracking”; center 960,600 → moved 1632,960 when head features moved |
| head model unit tests | iris changes do not affect prediction; head changes do; save/load preserves mode and predictions |
| old mode load test | legacy `iris8` without `control_mode` resolves to eyes |
| pointer fallback app test | real `EyeLensApp` with missing model: fallback active, engine “Mouse / touch”, overlay visible, lens setting on |
| pointer engine tests | pointer mode works with no camera/model and is idempotent |
| native lens hit-test | `WM_NCHITTEST` inside lens = HTCLIENT (1), outside = HTTRANSPARENT (-1) |
| native mapped click | physical click on lens at (399,274), source target center (349,249) received the click |
| native wheel | wheel -120 forwarded to the target under the lens |
| edge reach screenshot | lens centre reached (1918,1198) on 1920×1200; taskbar corner visible in clipped lens |
| head border grid | synthetic head calibration still 34 points, 0.0 px |
| global wheel listener | Ctrl+Alt+wheel up/down emitted `(0,1)` / `(0,-1)` |
| engine trim | prediction (500,400) + trim (40,-30) → (540,370) |

The synthetic E2E script lives outside the repo at
`C:\Users\avgrigorev\AppData\Local\Temp\opencode\head_calibration_e2e.py`.
It drives the actual calibration state machine with a fake tracker; it is not
part of the committed test suite.

## Real-Data Status

**No real head calibration has been run yet.** The algorithm is synthetic-tested
only. The next decisive step is the user’s real calibration:

1. Start eyeLens (`run.bat`). Settings should show **Control: Head**.
2. Click **Calibrate now**.
3. Aim the head at each dot — turn/move the head to face it, hold still.
4. Accept only if the measured error is ≤150 px; press Enter.
5. Test whether the lens follows the head, and whether it stays still while
   only the eyes move or blink.
6. Record `error_rmse`, whether the lens is usable, and any lag/overshoot.

The local `%LOCALAPPDATA%\eyeLens\calibration.json` is still an old rejected
eye/pose calibration. The first head calibration will overwrite it.

## Where We’re Going

1. **Real head calibration and acceptance test** (above). This is the
   decisive test of v0.10.
2. **No-camera acceptance test:** disable or occupy the camera, start eyeLens,
   and confirm the lens appears and follows the mouse or a finger on the
   touchscreen. Restore the camera and press **Apply**; with a head
   calibration present, tracking should resume automatically.
3. **Interactive/edge acceptance test:** click magnified buttons, right-click,
   double-click and scroll inside the lens; verify the real control receives
   the action. Point/look at the taskbar and corners; the lens should reach
   them and be partially clipped. Verify clicks outside the lens still pass
   through.
4. **Wheel trim acceptance test:** look at the top of the screen with the lens
   low; hold Ctrl+Alt and scroll up until it reaches the target; verify the
   same trim applies at other screen positions, persists across restart, and
   `Ctrl+Alt+0` clears it. Check that a mouse-drag correction still lands at
   the dropped point while trim is nonzero.
5. If head control works but feels too sensitive:
   - tune the global smoothing default or add a head-specific gain slider;
   - consider a small deadzone around the centre.
6. If the mapping quality is poor:
   - compare the six proxy features with MediaPipe’s raw 6-DOF pose features;
   - record per-point residuals before changing the model;
   - try a denser 6×6 head grid only if the error is a sampling problem.
7. Keep eye mode working; it shares the same model code but a different feature
   mask and calibration protocol.

## Risks & Blockers

- Real head data may be noisier or less linear than the synthetic mapping.
- The user must actually aim their head at the dots. Glancing with the eyes
  only produces a bad head calibration.
- Head control responds to posture changes. Sitting in a very different
  position after calibration moves the lens.
- Mode switching discards the in-memory model; only one calibration file is
  stored, so switching back may require recalibrating.
- Pointer fallback relies on the Windows pointer position. Touchscreens normally
  promote touch to pointer movement; a touch-aware app that suppresses pointer
  promotion may not update the lens. If that happens, the next step is a
  Windows pointer/raw-input listener rather than `QCursor.pos()`.
- Magnified input is implemented with `mouse_event` after warping the cursor.
  Windows UIPI blocks synthetic input to elevated (admin) apps. Drags inside
  the lens are not remapped; only clicks, double-clicks, right-clicks and the
  wheel. Hover/tooltips and cursor shapes are not forwarded.
- The lens is intentionally partially clipped at screen edges; that is how it
  reaches the taskbar. Users who prefer a fully visible lens could get an
  optional "keep lens on screen" toggle later.
- Ctrl+Alt+wheel is a global gesture. Apps that also react to it may scroll
  while the trim is adjusted; the overlay swallows it only when the pointer is
  over the lens.
- Trim is a global screen offset, not per-region; use `Ctrl+Alt+D` for local
  corrections.
- `Modelfile` in the repo root remains an unrelated untracked file; leave it.

## Exact State

- Repo: `https://github.com/Closegamer/eyeLens` (private, `main`)
- Version: `0.11.0`
- Code commits:
  - `3caf05b` — `feat: head-controlled lens with eye mode fallback (v0.9.0)`
  - `c1506c0` — `feat: mouse and touch pointer fallback when the camera is unavailable (v0.9.1)`
  - `10a5abe` — `feat: interactive lens clicks, edge-to-edge reach, head border targets (v0.10.0)`
  - `d44cece` — `feat: Ctrl+Alt+wheel lens fine trim (v0.11.0)`
- Tags: `v0.9.0`, `v0.9.1`, `v0.10.0`, `v0.11.0`
- Virtualenv: `C:\a_REPOS\eyeLense\.venv` (Python 3.12)
- Tests: 48 passed; ruff clean; smoke exit 0
- Settings default: `control_mode="head"`; schema remains 2
- Old calibration file is rejected on load

## Quick Start for Next Session

```powershell
cd C:\a_REPOS\eyeLense
# Read continue_session.md, then this handoff.

.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m eyelens --smoke-test

run.bat
# Calibrate: aim your head at each dot and hold still (~45 s).
# Check the measured error and whether the lens follows your head.
# If it does not: record the error, try Smoothing, then inspect the mapping.

# Pointer fallback (no camera):
# Disable/unplug the camera, start eyeLens, and confirm the lens follows the
# mouse or a finger. Restore the camera and press Apply in Settings.

# Interactive lens / edges:
# Move the lens over a button and click the magnified image; right-click and
# scroll. Point/look at the taskbar and corners; the lens should reach them.

# Fine trim:
# Look at the top of the screen. Ctrl+Alt+wheel up moves the lens up 10 px per
# notch. Ctrl+Alt+0 resets the trim.
```

Key files:

- `eyelens/gaze/features.py` — control modes, feature masks, mode persistence.
- `eyelens/gaze/model.py` — head/eye feature selection, v3 save/load.
- `eyelens/ui/calibration_window.py` — head aiming protocol and texts.
- `eyelens/ui/settings_window.py` — Control combo and mode help.
- `eyelens/gaze/engine.py` — head-mode gating/filtering, pointer fallback,
  runtime trim.
- `eyelens/app.py` — mode validation, calibration wiring, pointer fallback,
  trim hotkey/reset, status copy.
- `eyelens/hotkeys.py` — global keyboard hotkeys plus Ctrl+Alt+wheel listener.
- `eyelens/config.py` — settings including `trim_x`/`trim_y`.
- `eyelens/ui/overlay.py` — pointer-mode lens, edge-aware clamping, custom
  hit-test, mapped clicks/right-clicks/double-clicks/wheel.
