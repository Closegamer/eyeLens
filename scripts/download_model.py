"""Download the MediaPipe face landmarker model if it is not already present."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eyelens.config import ensure_model_path  # noqa: E402


def main() -> int:
    try:
        path = ensure_model_path()
    except Exception as exc:
        print(f"Could not download the model: {exc}", file=sys.stderr)
        return 1
    print(f"Face landmarker model: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
