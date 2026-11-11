from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from eyelens.config import ScreenInfo, Settings
from eyelens.gaze.engine import GazeEngine
from eyelens.gaze.features import FEATURE_NAMES
from eyelens.gaze.model import GazePrediction
from eyelens.gaze.tracker import TrackerSnapshot


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def make_engine() -> GazeEngine:
    screen = ScreenInfo("test", 0, 0, 1920, 1200, 1.0)
    return GazeEngine(screen, tracker=None, settings=Settings())


class StubModel:
    control_mode = "head"
    openness_threshold = 0.1

    def is_eye_open(self, openness: float) -> bool:
        return True

    def predict(self, features, head_pose=None) -> GazePrediction:
        return GazePrediction(500.0, 400.0)


class StubTracker:
    error_text = ""

    def __init__(self) -> None:
        self.seq = 0

    def snapshot(self) -> TrackerSnapshot:
        self.seq += 1
        return TrackerSnapshot(
            seq=self.seq,
            features=np.zeros(len(FEATURE_NAMES)),
            openness=0.3,
            face_found=True,
            timestamp=time.monotonic(),
            fps=30.0,
            head_pose=None,
        )


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


def test_camera_trim_is_added_to_prediction(qt_app) -> None:
    screen = ScreenInfo("test", 0, 0, 1920, 1200, 1.0)
    settings = Settings(trim_x=40, trim_y=-30)
    engine = GazeEngine(screen, tracker=StubTracker(), settings=settings)
    engine.set_model(StubModel())
    engine.poll()
    center = engine.current_center()
    assert center is not None
    assert center[0] == pytest.approx(540.0)
    assert center[1] == pytest.approx(370.0)
