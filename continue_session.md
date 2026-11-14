# eyeLens — Continue Session

**Memory:** `plans/handoffs/HANDOFF_eyelens-i18n_2026-11-14.md`
**Status:** v0.12.0 Russian / English UI + layout-independent hotkeys, tested,
**committed and pushed**.
**Repo:** `C:\a_REPOS\eyeLense` (branch `main`)
**Previous:** `plans/handoffs/HANDOFF_eyelens-head-control_2026-11-12.md`

## Current state

- `eyelens/i18n.py` provides `tr()` with 254 Russian translations and
  `auto | en | ru` language resolution. `auto` follows the Windows UI
  language; this PC resolves to `ru`.
- `Settings.language` defaults to `auto`; the settings header has
  **System / English / Русский** and switches live.
- All user-facing UI is translated: settings, calibration, overlay OSD, tray,
  notifications, camera errors.
- Global hotkeys match Windows virtual-key codes, so `Ctrl+Alt+L` and the other
  nine combos work in any keyboard layout; auto-repeat is ignored.
- Version `0.12.0`; settings badge `v0.12`; README updated.
- Tests: 54 passed; ruff clean; compileall clean; smoke test exit 0.
- Committed as `6f72b68` and pushed to `origin/main`. `Modelfile` is an
  unrelated pre-existing untracked file; leave it.
- `%LOCALAPPDATA%\eyeLens\settings.json` has `"language": "auto"`.

## Next

1. Restart eyeLens (tray → Quit, then `run.bat`) to load the hotkey fix.
2. Confirm Ctrl+Alt+L and the other hotkeys in Russian and English layouts.
3. Switch System → English → Русский; settings and tray menu should update
   immediately.
4. Run one Russian head calibration and check intro/result screens.
5. If accepted: tag `v0.12.0`.

## Quick checks

```powershell
cd C:\a_REPOS\eyeLense
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m eyelens --smoke-test
```

## Known limits

- CLI `--help` and stderr logs stay English.
- An open calibration window does not retranslate mid-run.
- An already displayed camera error keeps its original language until refresh.
