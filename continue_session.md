# eyeLens — Continue Session

**Memory:** `plans/handoffs/HANDOFF_eyelens-shapes-big-lens_2026-11-09.md`
**Status:** v0.4.0 implemented, tested and pushed. Nothing running. Real desktop
visual check and real-face calibration are the pending tests.
**Repo:** `https://github.com/Closegamer/eyeLens` (private, branch `main`)
**Code commit:** `d0d9454` · tag `v0.4.0`
**Chain:** `standalone-08a28c4a` seq 4

## What changed in v0.4.0

- **Lens shape choice** in Settings → Lens → Shape:
  - Round (ellipse)
  - Square (rounded rectangle)
  - Wide (1.6× wider rounded rectangle)
- **Size range** is now 120–1200 px high. Wide lenses can be up to 1920 px wide.
- **Big lens on demand**: `Ctrl+Alt+B`, tray **Big lens**, or settings **Big
  lens**. It toggles to 85% of the screen height and back to the previous size.
- Capture is now rectangular (`CaptureRequest` carries width/height), so wide
  lenses capture a wide source without stretching.
- Overlay shadow/vignette/ring/OSD/loading all follow the selected shape.
- Shape is persisted in `settings.json`; old settings default to Round.
- Version `0.4.0`.

## What is next

1. Run `run.bat`, switch between Round / Square / Wide, and try `Ctrl+Alt+B`.
   Check the real shadow, vignette, corner radius, and wide capture at max size.
2. If 1.6× wide is not the right aspect, change `Settings.WIDE_ASPECT`.
3. If square/wide corners should be sharp, set the corner radius to 0 in
   `LensOverlay._lens_path`.
4. Real-face calibration and mouse-correction quality are still pending from
   v0.2/v0.3. Read the prior handoffs for those.

## Exact state

- Virtualenv: `C:\a_REPOS\eyeLense\.venv` (Python 3.12).
- Version: `0.4.0`.
- Tests: 28 passed; ruff clean; smoke test exit 0; offscreen render checks for
  all three shapes pass.
- `Modelfile` in the repo root is still an unrelated pre-existing file; leave it
  untracked.
- This memory file and the v0.4 handoff are committed in the session commit
  after `d0d9454`.
