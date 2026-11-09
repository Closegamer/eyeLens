# eyeLens — gaze-controlled magnifying screen lens, MVP complete

**Date:** 2026-11-09
**Status:** COMPLETED
**Bead(s):** none
**Epic:** none
**Chain:** `standalone-08a28c4a` seq `1`
**Parent:** `none — first in chain`
**Prior chain:** `none — first in chain`

---

## Reference Documents

- `README.md` — product overview, setup, hotkeys, architecture, privacy, troubleshooting.
- `models/README.md` — face landmarker model source and Apache-2.0 attribution.
- `docs/settings.png` — settings UI screenshot.
- `docs/calibration.png` — calibration UI screenshot.
- `docs/icon.png` — generated app icon.

## The Goal

Build **eyeLens**: a screen lens with variable size that sits on the upper
screen layer, moves with the user's eyes after webcam calibration, and produces
a controllable zoom effect of the area the user is looking at.

The user supplied the new repo `https://github.com/Closegamer/eyeLens.git` and
asked for the implementation, then asked for a handoff and computer shutdown
when development was finished. The deliverable is a working Windows desktop MVP
with a real click-through overlay, webcam tracking, per-user calibration, zoom
and size controls, persistence, tray and global hotkeys.

## Where We Are

- Created the complete Python project from an empty repo (only an unrelated
  `Modelfile` existed; it was left untouched and untracked).
- Built an always-on-top, click-through, circular magnifying overlay with
  variable diameter (120–600 px), zoom (1×–6×), opacity, outline, OSD, soft
  shadow, vignette, fade-in/out, and a freeze mode.
- Verified the overlay is truly click-through: `WindowFromPoint` over the lens
  returned the underlying window, not the overlay; exstyle was `0x80800a8`
  (TOPMOST, TRANSPARENT, TOOLWINDOW, LAYERED, NOACTIVATE).
- Verified self-capture exclusion: `SetWindowDisplayAffinity(hwnd, 0x11)`
  returns true and `GetWindowDisplayAffinity` reads back `0x11`. A magenta
  test window was invisible to an `mss` grab at its center (captured desktop
  pixel instead of magenta).
- Implemented MediaPipe Face Landmarker tracking in a QThread with camera
  selection, MSMF 720p first, fallbacks to DirectShow/auto 480p, mirrored
  camera preview, iris/eye overlays, FPS reporting, preview reference counting,
  and clean shutdown.
- Implemented 14 scale-invariant gaze features (iris position per eye, averaged
  iris, vergence, head yaw/pitch/roll proxies, face position, face scale) and a
  40-term polynomial expansion.
- Implemented per-user calibration: 5×5 targets (25 points), ~0.45 s settle +
  ~1.05 s sample per point, per-point blink/outlier rejection, ridge regression
  with grouped leave-one-point-out alpha selection, quality metrics, and JSON
  persistence.
- Implemented runtime smoothing and loss handling: 1€ filter mapped from a
  0–100 smoothing slider, blink gating using the calibrated openness threshold,
  prediction bounds, stale-gaze fade, and screen-edge clamping.
- Built the full-screen calibration UI: camera preview, face status, 25-dot
  grid, progress counter, countdown, settle/sample/fit/result/error phases,
  automatic start when a face is detected, keyboard controls, and screen-sleep
  inhibition.
- Built the settings/status window with a dark custom Qt theme, camera preview,
  status rows, sliders, calibration/camera controls, hotkey reference and quit;
  added tray integration and global hotkeys (`Ctrl+Alt+L/F/C`, `=`, `-`, `]`,
  `[`) plus zoom/size menu actions and notifications.
- Added demo mode (`--demo`, `--smoke-test`) where the lens follows the mouse;
  this is how the UI and lens were tested without a face in front of the camera.
- Bundled `models/face_landmarker.task` (3,758,596 bytes) for offline first run,
  with auto-download fallback to `%LOCALAPPDATA%\eyeLens\models\`.
- Final gates passed: `ruff check .` clean, `pytest` 18/18, `compileall` clean,
  `python -m eyelens --smoke-test` exits 0.
- Code committed as `44701b0` (`feat: eyeLens gaze-controlled magnifier MVP`),
  tagged `v0.1.0`, and pushed to the private GitHub repo `Closegamer/eyeLens`.
- Live camera reached `READY`, opened calibration and delivered a preview;
  face detection was false because no person was in front of the camera.
- Synthetic calibration E2E completed all 25 points, produced 275 samples and
  leave-one-point-out RMSE 0.2 px, and emitted `finished` after simulated Enter.

## What We Tried (Chronological)

1. **Chose the desktop stack.** Considered Electron + WebGazer + transparent
   window, and C#/WPF + eye-tracking libraries. Chose Python 3.12 + PySide6 +
   OpenCV/MediaPipe + mss because it gives direct control over the overlay,
   screen capture, calibration math, and global hotkeys without a browser
   runtime. Rejected Electron because WebGazer calibration and a second
   capture/overlay process add complexity; rejected C# because webcam gaze
   estimation would still require an ML model and calibration pipeline.
2. **Validated screen capture performance.** Full-screen `mss` grab plus
   `QImage.copy()` measured **29.2 ms/frame (~34 fps)** at 1920×1200. That was
   acceptable but wasteful, so the final design captures only a padded square
   around the lens (margin 1.35× the magnified source).
3. **Validated capture exclusion.** Created a magenta fullscreen layered window,
   called `SetWindowDisplayAffinity(0x11)`, then grabbed the screen center with
   mss. The grab returned the desktop pixel `(128,128,128)`, not magenta. This
   confirmed the no-feedback approach works on this Windows build.
4. **Benchmarked camera backends.** DirectShow at 720p delivered **10 fps**
   (~100 ms/frame), DirectShow 480p **30 fps**, MSMF 720p **30 fps**, MSMF 480p
   **30 fps**. MediaPipe inference itself measured **7.2 ms/frame**. Final
   tracker tries MSMF 720p first, then DirectShow 480p, then auto 480p.
5. **Validated MediaPipe.** Downloaded the face landmarker model (3.6 MB),
   loaded it with `RunningMode.VIDEO`, ran it on a blank frame, and confirmed no
   crash and zero faces. Later live camera runs confirmed the preview pipeline
   and model load on the actual FHD camera.
6. **Built the calibration math.** Started with a simple ridge mapping, then
   discovered 25 points × 40 features needs stronger validation. Switched alpha
   selection to grouped leave-one-point-out cross-validation, which measures
   spatial generalization instead of leaking correlated frames from the same
   target. Per-frame samples are kept after per-target blink/MAD filtering.
7. **Tested calibration E2E synthetically.** A fake tracker generated features
   from the current target dot. Accelerated phases (0.15 s countdown, 0.05 s
   settle, 0.18 s sample) completed all 25 points, fit 275 samples, produced
   RMSE 0.2 px, and showed the result screen. First run timed out because the
   result waits for Enter; the follow-up test simulated Enter and verified the
   `finished` signal.
8. **Built the overlay rendering.** Used Qt translucent fullscreen window,
   `WindowTransparentForInput`, Windows exstyles, WDA exclusion, dirty-rect
   repainting, source/destination intersection mapping for screen edges, and a
   radial shadow. Tested with the debug env var
   `EYELENS_NO_CAPTURE_EXCLUDE=1`; the visible feedback mirror confirmed the
   debug mode, while the real mode uses WDA exclusion.
9. **Tested controls.** Simulated Ctrl+Alt+= twice and Ctrl+Alt+] via pynput
   while the app was running: zoom changed 2.0 → 2.5 and size 280 → 320. Toggled
   freeze: amber ring and “Lens locked” OSD rendered correctly.
10. **Polished and linted.** Generated settings/calibration docs screenshots
    with synthetic camera imagery (no personal desktop content), added ruff
    config, fixed import/order/style issues, and reran all tests and smoke
    checks after refactors.

## Key Decisions

- **Windows-first.** The no-feedback capture exclusion is Windows-specific.
  README and pyproject now mark Windows 10/11 only. Cross-platform was rejected
  for the MVP because a self-capturing lens produces an infinite mirror.
- **PySide6, not Electron.** One process, direct Windows API access for
  click-through and WDA, precise logical/physical DPI mapping, and no web stack.
- **MediaPipe Face Landmarker, not a dedicated eye tracker.** Works with ordinary
  webcams, includes 478 landmarks and both iris centers, and runs at 30 fps here.
- **Per-user ridge regression.** Chosen over k-NN or an MLP because it is fast,
  transparent, easy to persist/refit, and robust with a few hundred samples.
  Grouped leave-one-point-out CV was chosen over random K-fold to avoid
  correlated-frame leakage.
- **25-point 5×5 calibration.** Chosen over 9 points for better edge coverage.
  Takes ~37.5 s of sampling. Rejected 4×4 because screen-edge accuracy matters
  for a lens.
- **Capture only around the lens.** Full-screen capture measured 29.2 ms/frame;
  padded local capture is cheaper and keeps high zoom usable. The overlay maps
  partial source rects correctly when the lens is near a screen edge.
- **WDA_EXCLUDEFROMCAPTURE.** The only practical way to avoid the lens filming
  itself. Failure logs a warning; no silent flicker workaround.
- **Primary display only for the MVP.** The overlay, calibration targets, and
  capture all target the primary screen. Multi-monitor was deferred rather than
  half-supported.
- **Bundled model + auto-download fallback.** First checkout works offline; pip
  installs without the binary can download at first run.

## Evidence & Data

### Environment

| Item | Value |
| --- | --- |
| OS | Windows NT 10.0.26100 (Windows 11 24H2 class) |
| Display | 1920×1200 primary, NVIDIA RTX 5070 Ti Laptop GPU |
| Cameras | FHD Camera (index 0 usable); FHD IR Camera (index 1 not opened) |
| Python | 3.12.10 (venv at `C:\a_REPOS\eyeLense\.venv`) |
| Key packages | mediapipe 0.10.35, PySide6 6.12.0, opencv-contrib-python 4.14.0.94, mss 10.2.0, numpy 2.5.4, pynput 1.8.2 |
| Repo | `https://github.com/Closegamer/eyeLens` (private) |
| Commit / tag | `44701b0` / `v0.1.0` |

### Benchmarks

| Test | Result |
| --- | --- |
| mss full-screen grab + QImage copy | 29.2 ms/frame, ~34 fps |
| MediaPipe FaceLandmarker inference | 7.2 ms/frame average (720p input) |
| DirectShow 1280×720 read | 10.0 fps |
| DirectShow 640×480 read | 30.2 fps |
| MSMF 1280×720 read | 30.2 fps |
| MSMF 640×480 read | 30.3 fps |
| Calibration flow, synthetic | 25 points, 275 samples, LOO RMSE 0.2 px, Excellent |

### Windows integration

| Check | Result |
| --- | --- |
| WDA exclusion test | `SetWindowDisplayAffinity` true; screen center grabbed desktop gray instead of magenta |
| Affinity readback | `0x11` (`WDA_EXCLUDEFROMCAPTURE`) |
| Overlay exstyle | `0x80800a8` = TOPMOST + TRANSPARENT + TOOLWINDOW + LAYERED + NOACTIVATE |
| Click-through test | `WindowFromPoint(760,640)` returned underlying hwnd, not overlay hwnd |
| Hotkey simulation | zoom 2.0 → 2.5 (two presses), size 280 → 320 |
| Synthetic calibration accept | `finished` emitted after simulated Enter; n_points=25, n_samples=275, RMSE=0.2 |
| Final unit tests | 18 passed |
| Ruff | All checks passed |
| Smoke test | `python -m eyelens --smoke-test` exit 0 |

### Calibration grid and timing

- X fractions: 0.05, 0.275, 0.5, 0.725, 0.95.
- Y top: `max(0.16 * screen_height, 195 px)`, bottom: `0.90 * screen_height`.
- 5×5 targets; center-first not used; row-major order.
- Per point: 0.45 s settle + 1.05 s sample; ~37.5 s total sampling.
- Retry once per point if fewer than 6 clean samples; abort to error screen after
  a second failure.

## Code Analysis

- `eyelens/gaze/features.py`: 14 features — iris position per eye (4), averaged
  iris (2), vergence (2), head yaw/pitch/roll (3), face x/y/scale (3). Eye
  corners are sorted by screen x so both iris ratios move together; iris x is a
  roll-tolerant projection, iris y is relative to the lid midpoint, openness is
  lid height / eye width. Expansion: 40 terms (14 linear + 12 squares + 14
  interactions).
- `eyelens/gaze/model.py`: `_ALPHAS = np.logspace(-3, 4, 15)`; centered ridge
  with intercept and grouped per-target CV. Quality: ≤80 px Excellent, ≤150 px
  Good, ≤240 px Fair, else Needs recalibration (`quality_ok` = ≤150 px).
  Runtime inputs clipped to calibration min/max ±20% of each range.
- `eyelens/gaze/engine.py`: smoothing maps to 1€ `min_cutoff` 4.0 → 0.42 Hz
  logarithmically, beta 0.045 → 0.008. Predictions outside screen +18% are
  ignored; predictions clamp to the screen; lens is live only under 0.55 s age.
- `eyelens/gaze/tracker.py`: MSMF 720p first, DirectShow/auto 480p fallbacks;
  preview 480×270 at 15 fps, mirrored, with iris/eye/face overlays; monotonic
  VIDEO timestamps; `ready` only after camera open, `_fail` sets error text.
- `eyelens/capture.py`: margin 1.35, 30 fps local padded square; physical/logical
  scale derived from mss vs Qt; `CaptureFrame` carries the requested center so
  overlay source intersection is exact at screen edges.
- `eyelens/ui/overlay.py`: fullscreen Qt `Tool` + `WindowTransparentForInput`;
  WDA on show; center easing 0.022 s, diameter 0.09 s, fade 0.10/0.14 s, shadow
  26 px; dirty rect = old ∪ new bounds; OSD fade 0.35 s; amber ring when frozen.
- `eyelens/ui/calibration_window.py`: INTRO → COUNTDOWN → SETTLE → SAMPLE →
  RETRY/FIT → RESULT/ERROR; per-point MAD 4.25σ then 4.0σ; openness threshold
  max(0.055, median × 0.55); screen-sleep prevention.
- `eyelens/app.py`: owns settings, model, tracker, engine, capture, overlay,
  settings window, tray, hotkeys, screen-change handling, debounced persistence;
  uses `contextlib.suppress` only for best-effort hardware/Qt cleanup.
- `eyelens/ui/settings_window.py`: dark stylesheet, custom preview, status
  provider callback, 450 ms status timer, centering on primary screen.
- `eyelens/hotkeys.py`: pynput `GlobalHotKeys`; avoids Ctrl+Alt+Arrow conflicts.

## Files Changed

### Source code

- `eyelens/__init__.py` — version, app name, early MediaPipe/TensorFlow env setup.
- `eyelens/__main__.py` — `python -m eyelens` entry point.
- `eyelens/app.py` — controller, tray, hotkeys, CLI, lifecycle, screen changes.
- `eyelens/capture.py` — padded 30 fps screen capture thread.
- `eyelens/config.py` — paths, settings dataclass, calibration storage helpers,
  model discovery/download, screen info.
- `eyelens/hotkeys.py` — global hotkey manager.
- `eyelens/gaze/__init__.py` — package exports.
- `eyelens/gaze/features.py` — landmark → 14 features, 40-term expansion.
- `eyelens/gaze/filters.py` — 1€ filter and 2D wrapper.
- `eyelens/gaze/model.py` — calibration fit, grouped CV, save/load, quality.
- `eyelens/gaze/tracker.py` — camera + MediaPipe thread and preview.
- `eyelens/gaze/engine.py` — prediction, smoothing, demo mode, status.
- `eyelens/ui/__init__.py` — package marker.
- `eyelens/ui/calibration_window.py` — full-screen calibration flow.
- `eyelens/ui/icon.py` — programmatic icon/pixmap.
- `eyelens/ui/overlay.py` — always-on-top click-through lens.
- `eyelens/ui/settings_window.py` — settings/status/camera preview.

### Tests

- `tests/test_features.py` — feature shape, iris direction consistency, blink
  openness, head translation, expansion length.
- `tests/test_model.py` — synthetic fit/predict, quality metrics, openness
  threshold, save/load roundtrip, too-few-points rejection.
- `tests/test_filters.py` — 1€ filter pass-through, constant signal, step
  response, 2D reset.
- `tests/test_settings.py` — normalization, persistence, invalid file defaults,
  screen matching, dict roundtrip.

### Docs & data

- `README.md` — full product/setup/architecture/troubleshooting docs.
- `docs/settings.png` — settings UI screenshot.
- `docs/calibration.png` — calibration UI screenshot.
- `docs/icon.png` — 512 px icon.
- `models/face_landmarker.task` — 3,758,596-byte MediaPipe model.
- `models/README.md` — model source/license.

### Config & tooling

- `pyproject.toml` — package metadata, dependencies, ruff/pytest config.
- `requirements.txt`, `requirements-dev.txt` — runtime/dev dependencies.
- `run.bat` — creates `.venv` with `py -3.12`, installs, launches (CRLF).
- `.gitignore`, `.gitattributes`, `LICENSE`.
- `.github/workflows/tests.yml` — ruff + pytest on Ubuntu.

## User Feedback & Preferences (REQUIRED — never omit)

- User described the core product in their own words: “screen lense with variable
  size that would be at upper screen layer, moved by eyes of user after
  calibrating camera and makes controllable zoom effect of the area that user
  looks at”. All four requirements were treated as hard requirements.
- User supplied `https://github.com/Closegamer/eyeLens.git` and called it a “new
  repo”; implementation was expected in that repo, not a separate prototype.
- User then said: “i have to go now. when you finish with development, please
  make handoff command and shut down the computer”. This session must end with
  a file-based handoff and a real shutdown, not a paste prompt.
- Global preference applies: never ask the user to paste handoff/next-session
  text; write memory files and let the next session read them automatically.
- No corrections to UI style or feature scope were given during the build; the
  design choices above were made autonomously.

## Where We're Going

1. **Real-face calibration on this machine.** Launch `run.bat`, keep a face in
   the FHD camera, complete all 25 points, and record the actual LOO RMSE and
   subjective accuracy. This is the main unverified item.
2. **Tune accuracy if needed.** If gaze is too jittery or offset, inspect the
   calibration samples (`%LOCALAPPDATA%\eyeLens\calibration.json`), adjust the
   feature set/grid, and consider adding a short validation target set after fit.
3. **Add a camera pause / privacy toggle.** Tray and settings control to stop
   the tracker without quitting; lens should freeze or fade.
4. **Multi-monitor support.** Overlay per monitor, calibration target selection,
   screen-specific models, and primary-screen change handling.
5. **Packaging.** PyInstaller one-folder build with the model and an optional
   installer/start-with-Windows setting.
6. **Lens refinements.** Rectangular/elliptical shape, dwell-to-freeze,
   per-app profiles, and possibly adjustable edge softness.

## Risks & Blockers

- **Real gaze accuracy is unverified.** All automated tests were synthetic or
  camera-without-face. Webcam gaze estimation can be ±100–250 px depending on
  lighting, glasses, head pose, and camera placement. The product works
  mechanically but may need calibration/feature tuning with the actual user.
- **WDA availability.** On Windows builds older than 2004 or unusual graphics
  drivers, self-capture exclusion may fail and the lens will show feedback. The
  app logs a warning; no fallback is implemented.
- **Single primary monitor only.** Calibration data is invalidated when the
  primary screen geometry changes; a second monitor is not covered.
- **Hotkey conflicts.** Ctrl+Alt combinations are generally safe but can be
  intercepted by vendor utilities. The hotkey map is in `eyelens/hotkeys.py`.
- **Python version.** MediaPipe support is pinned to Python <3.13; `run.bat`
  explicitly uses `py -3.12`.
- **MediaPipe C++ logs** still appear on stderr despite env/absl suppression.
  Cosmetic only; use `pythonw`/packaged build for a console-free experience.

## Open Questions

- What real-world accuracy will the user get, and is a 280 px / 2.0× default
  lens comfortable? Adjust defaults after a real calibration.
- Should the camera stop automatically when the lens is hidden or the user is
  idle, or is an explicit pause control sufficient?
- Should calibration files be tied to camera index in a stricter way? Currently
  a camera-index mismatch is only warned about in settings.
- Is a 5×5 grid the right tradeoff, or would 3×3 + edge points be faster with
  similar accuracy for this user?

## Quick Start for Next Session

```bash
# Repo and memory
cd C:\a_REPOS\eyeLense
# Read: continue_session.md, then this handoff
# Repo: https://github.com/Closegamer/eyeLens (private)
# Branch: main, commit 44701b0, tag v0.1.0

# Verify toolchain
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .

# Run the product
run.bat
# Demo without camera:
.\.venv\Scripts\python.exe -m eyelens --demo

# Key files to read first
#   eyelens/gaze/features.py
#   eyelens/gaze/model.py
#   eyelens/gaze/engine.py
#   eyelens/gaze/tracker.py
#   eyelens/ui/overlay.py
#   eyelens/ui/calibration_window.py

# Evidence paths
#   %LOCALAPPDATA%\eyeLens\settings.json
#   %LOCALAPPDATA%\eyeLens\calibration.json   (after a real calibration)
#   docs/settings.png, docs/calibration.png

# Next action
# Complete a real-face 25-point calibration with the FHD camera (index 0) and
# measure actual accuracy before changing the algorithm.
```

## Session Closed

**Closed at:** 2026-11-09T16:43:27+03:00
**Commit:** `session: eyelens-mvp [standalone-08a28c4a]` (includes this handoff;
MVP code commit is `44701b0`)
**Session status:** Handed off to next session. The computer is being shut down
at the user's explicit request after the handoff commit is pushed.
