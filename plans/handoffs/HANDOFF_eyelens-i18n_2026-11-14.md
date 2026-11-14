# eyeLens — Russian / English interface (v0.12.0)

**Date:** 2026-11-14 (updated 2026-11-15)
**Status:** IMPLEMENTED + hotkey fix — committed as `6f72b68`, awaiting a
quick real-app acceptance check
**Parent:** `HANDOFF_eyelens-head-control_2026-11-12.md`

## Request

> “make language switch - Russian / English and translate into Russian. By
> default app should determine windows current language”

## What Changed

- **New `eyelens/i18n.py`.**
  - `tr("English text")` returns the Russian translation, or the English text
    when a key is missing.
  - `system_language()` uses `GetUserDefaultUILanguage()` on Windows (primary
    language id `0x19` = Russian), with a locale fallback.
  - `resolve_language()` maps `auto` to the Windows language and accepts
    `en` / `ru`.
  - 254 English source strings translated to Russian.
- **Settings.**
  - `Settings.language` defaults to `"auto"`; normalized to `auto|en|ru`.
  - Old `settings.json` files without the field load as `auto`.
  - Language combo is in the settings header: **System / English / Русский**.
  - Changing it applies immediately.
- **Live switch.**
  - `EyeLensApp` applies the saved language before building the UI.
  - On change, tray action texts are updated and the settings window is
    rebuilt with the new language (same settings object, signals rewired).
  - Calibration windows created later use the current language; overlay OSD
    and tray notifications are translated at call time.
- **Translated surfaces.**
  - Settings window, tooltips, preview placeholders, hotkey list, language
    combo.
  - Full-screen calibration (intro, countdown, retry/error, result, HUD).
  - Overlay OSD, correction handle tooltip, tray menu, notifications, camera
    error messages, startup error.
  - Internal English state labels (`engine.state_text()`, `model.summary()`)
    stay unchanged for tests and status-level mapping; they are translated
    only for display.
- **Layout fixes for Russian.**
  - Settings label widths are minimums instead of fixed widths.
  - Calibration intro card grew from 560×184 to 560×260 because the Russian
    instructions were clipped.
- **Version / docs:** `0.12.0`, settings badge `v0.12`, README feature and
  settings bullets.
- **Tests:** new `tests/test_i18n.py` checks system detection, RU lookup and
  English fallback, settings roundtrip, and that every literal passed to
  `tr()` in the package has a Russian entry.

## Hotkey Fix (same release)

`pynput.GlobalHotKeys` matched characters, which fails while Ctrl+Alt are held
(pynput reports no character) and under a non-Latin layout. `HotkeyManager` now
uses a raw `keyboard.Listener` and Windows virtual-key codes, with auto-repeat
suppressed, so all ten combos work in any keyboard layout. New
`tests/test_hotkeys.py`.

## Verification

| Check | Result |
| --- | --- |
| `pytest -q` | 54 passed |
| `ruff check .` | clean |
| `python -m compileall -q eyelens` | clean |
| `python -m eyelens --smoke-test` | exit 0 |
| default `auto` on this PC | resolves `ru` (Windows UI language is Russian) |
| live switch ru → en → ru with real `EyeLensApp` | settings window rebuilt, tray text changed, combo persisted |
| Russian settings screenshot | labels fit, header/combo fits |
| Russian calibration intro, head + eyes | text fits after card enlargement |
| Russian calibration result | fits |
| synthetic Ctrl+Alt+L through the real global hook | `toggle_lens` fired |

Screenshots used for the check:
`C:\Users\avgrigorev\AppData\Local\Temp\opencode\settings_ru_real.png`,
`calibration_ru_head.png`, `calibration_ru_eyes.png`,
`calibration_ru_result.png`.

`%LOCALAPPDATA%\eyeLens\settings.json` was restored to `"language": "auto"`.

## Key Decisions

- **English source strings as dictionary keys.** Missing translations fall back
  to readable English instead of showing raw `some.key` identifiers.
- **Rebuild the settings window on language change.** It is a single build
  function; rebuilding is less code and less error-prone than retranslating
  every widget in place.
- **Keep internal status labels English.** `engine.state_text()` and
  `model.summary()` are also asserted by tests and used as mapping keys;
  translation happens at the display boundary.
- **No Qt `.ts`/`.qm` files.** The app has one window and a few painted
  screens; a 250-entry Python dict is the smallest complete solution.

## Known Limitations

- CLI `--help` text and stderr log lines stay English.
- Switching language while the full-screen calibration is already open does
  not retranslate that open window; the next calibration uses the new language.
- A tracker error message that is already on screen keeps the language it was
  emitted in until it refreshes.
- The settings preview keeps `LIVE` untranslated (universal indicator).

## Exact State

- Version: `0.12.0`
- Repo: `C:\a_REPOS\eyeLense`, branch `main`
- Changed: `eyelens/app.py`, `eyelens/config.py`, `eyelens/i18n.py` (new),
  `eyelens/gaze/tracker.py`, `eyelens/hotkeys.py`,
  `eyelens/ui/settings_window.py`, `eyelens/ui/calibration_window.py`,
  `eyelens/ui/overlay.py`, `eyelens/ui/correction_handle.py`,
  `tests/test_i18n.py` (new), `tests/test_hotkeys.py` (new), `README.md`,
  `pyproject.toml`, `eyelens/__init__.py`
- Tests: 54 passed; ruff clean; compileall clean; smoke exit 0
- Committed as `6f72b68` and pushed to `origin/main`.
- `Modelfile` is still the unrelated pre-existing untracked file; leave it.

## Next Session

1. Restart eyeLens (tray → Quit, then `run.bat`) to load the hotkey fix.
2. Confirm **Ctrl+Alt+L** and the other hotkeys in Russian and English layouts.
3. Confirm the Russian UI appears by default; switch
   **System → English → Русский** and check the window and tray menu.
4. Run one head calibration in Russian and check the intro/result screens.
5. Tag `v0.12.0` if the acceptance check passes.
