# eyeLens — lens shapes and Big lens (v0.4.0)

**Date:** 2026-11-09
**Status:** IMPLEMENTED — awaiting real visual check on the desktop
**Bead(s):** none
**Epic:** none
**Chain:** `standalone-08a28c4a` seq `4`
**Parent:** `HANDOFF_eyelens-mouse-correction_2026-11-09.md`
**Prior code commit:** `9500bd7` / follow-up `632cd1e`, tag `v0.3.0`

---

## The Goal

The user asked:

> “it must be choise - round lense or square or wide square”

and earlier:

> “lens should have bigger size on demand”

So: a persisted shape choice between **Round**, **Square**, and **Wide** (a
1.6× wider rectangle), and a quick way to get a much larger lens without
dragging the size slider.

## What Was Built

- **Shape setting** (`Settings.shape`, values `round`, `square`, `wide`):
  - default `round`, persisted in `settings.json`
  - invalid values normalise back to `round`
  - `lens_dimensions(shape, diameter)` returns `(width, height)`; `diameter` is
    always the height, and `wide` uses `width = height × 1.6`
- **Settings UI**: a **Shape** combo box (Round / Square / Wide) in the Lens
  card, above Size. The Size value shows width×height for wide lenses.
- **Overlay rendering**:
  - round uses an ellipse; square/wide use a rounded rectangle (14 px corner
    radius)
  - clip path, dark fill, captured image, vignette, ring, OSD, loading spinner,
    and shadow all follow the shape
  - the shadow is now a layered stroke around the shape instead of a circular
    radial gradient, so rectangles look correct
  - dirty-rect tracking uses width and height
- **Capture geometry**:
  - `CaptureRequest` now carries `width` and `height` instead of `diameter`
  - the screen capture area is a padded rectangle, so a wide lens captures a
    wide source without stretching
  - `source_extent(value, zoom)` is applied separately to width and height
- **Size range**: raised from 120–600 to **120–1200 px high**. Wide max is
  1920 px (fits a 1920-wide screen).
- **Big lens on demand**:
  - hotkey `Ctrl + Alt + B`
  - tray menu **Big lens**
  - settings **Big lens** checkable button
  - toggles to `preferred_big_diameter(screen_height)` = 85% of the logical
    screen height (capped at 1200) and restores the previous size
  - if the lens is already at/above the big size, it reports “Lens already …”
    instead of shrinking
  - changing the size slider or using the size hotkeys clears Big lens mode
- Version bumped to `0.4.0`.

## Verification Done

| Check | Result |
| --- | --- |
| `ruff check .` | clean |
| `pytest` | 28 passed |
| `compileall` | clean |
| `python -m eyelens --smoke-test` | exit 0 |
| offscreen render check | round, square, and wide all render without errors |
| offscreen app check | shape combo syncs, wide shape reaches overlay, invalid shape normalises to round |
| app Big lens check | 600 → 680 (offscreen screen height) and back to 600 |

**Not verified:** actual visual quality of square/wide shapes on the real
desktop (shadow, vignette, corner radius, wide capture at max size). A real-face
calibration is still the main pending accuracy test.

## Key Decisions

- **Height is the size dimension.** The slider and `diameter` control height;
  square and round are height×height, wide is 1.6×height wide. This makes
  changing shape predictable and keeps one persisted size value.
- **Rounded rectangle, not sharp square.** A 14 px corner radius keeps the
  square/wide shapes looking like a lens rather than a hard window; the shape
  is still clearly rectangular.
- **Rectangular capture, not a square capture.** Capturing a padded rectangle
  avoids stretching and wasted pixels for wide lenses.
- **Big lens is a session toggle.** It remembers the previous size; manual size
  changes cancel it. It is not persisted as a separate mode, so restarting with
  a big lens simply keeps that size.
- **85% of screen height.** A big lens that still shows the screen edges; 100%
  would touch the top/bottom and look clipped.

## Files Changed

- `eyelens/config.py` — `shape`, `lens_dimensions`, `preferred_big_diameter`,
  1200 max.
- `eyelens/capture.py` — width/height capture request and rectangular source.
- `eyelens/ui/overlay.py` — shape paths, rectangular rendering, shadow,
  rectangular dirty rect/capture request.
- `eyelens/ui/settings_window.py` — Shape combo, Big lens button, size labels,
  hotkey row, combo styling.
- `eyelens/app.py` — Big lens toggle, tray action, shape-aware OSD, clearing
  big mode on manual resize.
- `eyelens/hotkeys.py` — `Ctrl+Alt+B`.
- `README.md` — shapes, size range, Big lens, controls.
- `tests/test_settings.py` — shape normalization, lens dimensions, big preset.
- `pyproject.toml`, `eyelens/__init__.py` — version 0.4.0.

## Where We're Going

1. Run `run.bat`, open Settings, switch between Round / Square / Wide, and try
   `Ctrl+Alt+B`. Check the shadow/vignette and wide capture at maximum size.
2. If the 1.6× wide aspect is not right, change
   `Settings.WIDE_ASPECT` (one constant).
3. If square/wide corners should be sharp, set the corner radius to 0 in
   `LensOverlay._lens_path`.
4. Real-face calibration and mouse-correction quality are still the pending
   acceptance tests from v0.2/v0.3.

## Quick Start for Next Session

```powershell
cd C:\a_REPOS\eyeLense
# Read: continue_session.md, then this handoff
# Repo: https://github.com/Closegamer/eyeLens (private)
# Branch: main, commit d0d9454, tag v0.4.0

.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m eyelens --smoke-test

# Real product
run.bat
# Settings -> Shape; try Ctrl+Alt+B for Big lens.
```

## Session Closed

**Closed at:** 2026-11-09
**Commit:** `d0d9454` pushed to `origin/main`; tag `v0.4.0` pushed.
**Status:** Implemented and synthetically rendered. Real desktop visual check
remains.
