from __future__ import annotations

import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from eyelens.ui.calibration_window import CalibrationWindow, Phase


class _Tracker:
    error_text = ""

    def acquire_preview(self) -> None:
        pass

    def release_preview(self) -> None:
        pass

    def snapshot(self):
        return SimpleNamespace(face_found=True, features=None, seq=0, openness=1.0, fps=0.0)


def _window(control_mode: str = "head") -> CalibrationWindow:
    app = QApplication.instance() or QApplication([])
    return CalibrationWindow(_Tracker(), app.primaryScreen(), control_mode=control_mode)


def test_intro_waits_for_the_user() -> None:
    window = _window()
    window._phase = Phase.INTRO
    window._phase_started = time.monotonic() - 5.0
    window._tick()
    assert window._phase == Phase.INTRO


def test_preview_hides_only_for_targets_under_it() -> None:
    window = _window()
    screen = window.screen.geometry()
    top_left = min(window._points, key=lambda p: (p[1], p[0]))
    center = min(
        window._points,
        key=lambda p: (p[0] - screen.center().x()) ** 2
        + (p[1] - screen.center().y()) ** 2,
    )
    window._phase = Phase.SETTLE
    window._point_index = window._points.index(top_left)
    assert window._preview_would_cover_point()
    window._point_index = window._points.index(center)
    assert not window._preview_would_cover_point()
    window._phase = Phase.INTRO
    window._point_index = window._points.index(top_left)
    assert not window._preview_would_cover_point()
