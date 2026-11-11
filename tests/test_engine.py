from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from eyelens.config import ScreenInfo, Settings
from eyelens.gaze.engine import GazeEngine


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def make_engine() -> GazeEngine:
    screen = ScreenInfo("test", 0, 0, 1920, 1200, 1.0)
    return GazeEngine(screen, tracker=None, settings=Settings())


def test_pointer_fallback_works_without_camera_or_model(qt_app) -> None:
    engine = make_engine()
    assert engine.state_text() == "Not calibrated"
    engine.set_pointer_fallback(True)
    assert engine.pointer_fallback
    assert engine.state_text() == "Mouse / touch"
    assert engine.tracking_live()
    assert engine.eyes_open
    engine.poll()
    assert engine.current_center() is not None

    engine.set_pointer_fallback(False)
    assert not engine.pointer_fallback
    assert engine.state_text() == "Not calibrated"


def test_pointer_fallback_is_idempotent(qt_app) -> None:
    engine = make_engine()
    engine.set_pointer_fallback(True)
    engine.poll()
    first = engine.current_center()
    engine.set_pointer_fallback(True)
    engine.poll()
    assert engine.current_center() == first
