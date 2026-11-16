"""PyInstaller entry point: run eyeLens as a windowed app without a console."""

from __future__ import annotations

import sys

# A windowed build has no stdout/stderr; log errors instead of crashing prints.
if sys.stdout is None or sys.stderr is None:
    from eyelens.config import config_dir

    log = open(config_dir() / "eyeLens.log", "w", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives with the process
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log

from eyelens.app import main

if __name__ == "__main__":
    raise SystemExit(main())
