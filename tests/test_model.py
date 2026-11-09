from __future__ import annotations

import numpy as np
import pytest

from eyelens.config import ScreenInfo
from eyelens.gaze.features import FEATURE_NAMES
from eyelens.gaze.model import GazeModel

WIDTH = 1920
HEIGHT = 1200
SCREEN = ScreenInfo("test", 0, 0, WIDTH, HEIGHT, 1.0)


def make_dataset() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(7)
    xs = np.linspace(WIDTH * 0.08, WIDTH * 0.92, 5)
    ys = np.linspace(HEIGHT * 0.12, HEIGHT * 0.88, 5)
    samples: list[np.ndarray] = []
    targets: list[list[float]] = []
    point_ids: list[int] = []
    point = 0
    for y in ys:
        for x in xs:
            for _ in range(12):
                nx = x / WIDTH
                ny = y / HEIGHT
                iris_x = 0.18 + 0.64 * nx + rng.normal(0, 0.004)
                iris_y = 0.30 + 0.40 * ny + rng.normal(0, 0.004)
                yaw = 0.14 * (nx - 0.5) + rng.normal(0, 0.002)
                pitch = 0.10 * (ny - 0.5) + rng.normal(0, 0.002)
                values = np.zeros(len(FEATURE_NAMES))
                values[0] = iris_x
                values[2] = iris_x
                values[4] = iris_x
                values[1] = iris_y
                values[3] = iris_y
                values[5] = iris_y
                values[8] = yaw
                values[9] = pitch
                values[11] = 0.05 * (nx - 0.5)
                values[12] = 0.05 * (ny - 0.5)
                values[13] = 1.8
                samples.append(values)
                targets.append([x, y])
                point_ids.append(point)
            point += 1
    return (
        np.asarray(samples),
        np.asarray(targets),
        np.asarray(point_ids, dtype=np.int64),
    )


def test_fit_predict_and_metrics() -> None:
    samples, targets, point_ids = make_dataset()
    model = GazeModel.fit(
        samples, targets, point_ids, openness_threshold=0.12, screen=SCREEN.to_dict()
    )
    assert model.metrics.n_points == 25
    assert model.metrics.n_samples == len(samples)
    assert model.metrics.loo_rmse < 90.0
    assert model.metrics.worst_point_rmse < 180.0
    assert model.quality_ok

    xs = np.linspace(WIDTH * 0.08, WIDTH * 0.92, 5)
    ys = np.linspace(HEIGHT * 0.12, HEIGHT * 0.88, 5)
    for target in ([xs[1], ys[1]], [xs[3], ys[3]]):
        mask = np.all(targets == np.asarray(target), axis=1)
        mean_features = samples[mask].mean(axis=0)
        prediction = model.predict(mean_features)
        assert abs(prediction.x - target[0]) < 110
        assert abs(prediction.y - target[1]) < 110


def test_is_eye_open_uses_calibration_threshold() -> None:
    samples, targets, point_ids = make_dataset()
    model = GazeModel.fit(samples, targets, point_ids, 0.12, SCREEN.to_dict())
    assert model.is_eye_open(0.2)
    assert not model.is_eye_open(0.01)


def test_save_and_load_roundtrip(tmp_path) -> None:
    samples, targets, point_ids = make_dataset()
    model = GazeModel.fit(samples, targets, point_ids, 0.12, SCREEN.to_dict())
    path = tmp_path / "calibration.json"
    model.save(path)
    loaded = GazeModel.load(path)
    assert loaded is not None
    assert loaded.metrics.n_points == model.metrics.n_points
    prediction_a = model.predict(samples[0])
    prediction_b = loaded.predict(samples[0])
    assert abs(prediction_a.x - prediction_b.x) < 1e-6
    assert abs(prediction_a.y - prediction_b.y) < 1e-6


def test_rejects_too_few_points() -> None:
    samples, targets, _ = make_dataset()
    with pytest.raises(ValueError):
        GazeModel.fit(
            samples[:20],
            targets[:20],
            np.zeros(20, dtype=np.int64),
            0.12,
            SCREEN.to_dict(),
        )
