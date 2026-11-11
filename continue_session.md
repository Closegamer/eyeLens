# eyeLens — Continue Session

**Memory:** `plans/handoffs/HANDOFF_eyelens-head-control_2026-11-12.md`
**Status:** v0.10.0 implemented, tested, tagged. **Real head calibration and
interactive/edge acceptance tests pending.**
**Repo:** `https://github.com/Closegamer/eyeLens` (private, branch `main`)
**Code commits:** `3caf05b` (head control), `c1506c0` (pointer fallback),
`10a5abe` (interactive lens + edge reach)
**Tags:** `v0.9.0`, `v0.9.1`, `v0.10.0`
**Chain:** `standalone-08a28c4a` seq 9

## What changed in v0.10.0

- **Clicks now work on the magnified content.** The overlay used to be fully
  click-through, so clicking a zoomed button hit the screen at the wrong
  (unmagnified) spot. Now:
  - only the lens shape is hit-testable (`WM_NCHITTEST` returns HTCLIENT
    inside the lens, HTTRANSPARENT outside);
  - a click inside the lens is mapped with
    `source = lens_center + (click - lens_center) / zoom`;
  - the physical click is deferred until mouse release, then the cursor is
    warped to the source point, left/right/middle click is injected, and the
    cursor is restored;
  - the overlay is force-click-through for 60 ms while the synthetic click is
    delivered, so the lens cannot re-capture its own click;
  - double-click and vertical/horizontal wheel are forwarded too;
  - outside the lens, clicks/scroll pass through unchanged.
  - Dragging inside the lens is still not remapped; use click or wheel.
- **The lens reaches screen borders and corners.** `clamp_lens_center` now
  allows the lens centre to reach 0..screen width/height instead of staying a
  half-diameter inside. At an edge the lens is intentionally clipped; the
  visible part magnifies the taskbar/corner. Tested with the centre at
  (1918, 1198) on 1920×1200.
- **Head calibration targets now cover the borders:** head-mode grid x =
  0.03/0.265/0.5/0.735/0.97, y = 0.10..0.96. Eye mode keeps the old interior
  grid. This lets the head model predict the taskbar and corners.
- Version `0.10.0`.

## What is next

1. Restart eyeLens (`run.bat`).
2. Recalibrate head control if a 0.9.x head calibration exists (the new border
   dots improve edge/taskbar reach; old files still load but were trained on
   the interior grid).
3. Test clicking: open an app with buttons, move the lens over them, click the
   magnified button, right-click and scroll. Verify the click lands on the
   intended control.
4. Test edges: look/point at the Windows taskbar and screen corners. The lens
   should now reach them (it will be partially clipped).
5. Confirm clicks **outside** the lens still reach the desktop/taskbar normally.
6. If click mapping feels wrong, record the lens zoom, pointer position and
   where the click landed.
7. Test pointer fallback again with the camera unavailable.

## Exact state

- Virtualenv: `C:\a_REPOS\eyeLense\.venv` (Python 3.12).
- Version: `0.10.0`.
- Tests: 47 passed; ruff clean; compileall clean; smoke test exit 0.
- Native overlay tests (real desktop):
  - `WM_NCHITTEST`: inside lens = 1 (HTCLIENT), outside = -1 (HTTRANSPARENT).
  - Full-path click on lens image reached the target window at the mapped
    source coordinate; vertical wheel -120 was forwarded.
  - Edge screenshot: lens centre reached (1918, 1198) and showed the
    bottom-right taskbar corner.
- Synthetic head calibration E2E still passes (34 points, 0.0 px).
- `%LOCALAPPDATA%\eyeLens\calibration.json` is still an old rejected
  eye/pose calibration; the first head calibration overwrites it.
- `Modelfile` in the repo root is an unrelated pre-existing untracked file;
  leave it untracked.

## Known limitations

- Dragging/selecting inside the lens is not remapped yet; clicks, double-clicks,
  right-clicks and wheel are.
- Hover, tooltips and cursor-shape feedback from the underlying app are not
  forwarded through the lens.
- Synthetic input may be rejected by elevated (admin) apps.
- At screen edges the lens is partially off-screen by design.
