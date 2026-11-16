"""PyInstaller entry point: run eyeLens as a windowed app without a console."""

from __future__ import annotations

import os
import sys

# A windowed build has no stdout/stderr; prints in error paths must not crash.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115 - lives with the process
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115 - lives with the process

from eyelens.app import main

if __name__ == "__main__":
    raise SystemExit(main())
