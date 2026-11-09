from __future__ import annotations

import json

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


def test_independent_validation_error_is_used() -> None:
    samples, targets, point_ids = make_dataset()
    model = GazeModel.fit(
        samples,
        targets,
        point_ids,
        0.12,
        SCREEN.to_dict(),
        validation_rmse=42.0,
        validation_points=9,
    )
    assert model.metrics.validation_rmse == 42.0
    assert model.metrics.validation_points == 9
    assert model.error_rmse == 42.0
    assert model.summary().endswith("±42 px")


def test_model_ignores_head_and_face_features() -> None:
    samples, targets, point_ids = make_dataset()
    model = GazeModel.fit(samples, targets, point_ids, 0.12, SCREEN.to_dict())
    base = samples[50].copy()
    changed = base.copy()
    changed[8:] += 5.0
    first = model.predict(base)
    second = model.predict(changed)
    assert abs(first.x - second.x) < 1e-6
    assert abs(first.y - second.y) < 1e-6


def test_load_without_model_mode_uses_loo_estimate(tmp_path) -> None:
    samples, targets, point_ids = make_dataset()
    model = GazeModel.fit(
        samples,
        targets,
        point_ids,
        0.12,
        SCREEN.to_dict(),
        validation_rmse=42.0,
        validation_points=9,
    )
    raw = model.to_dict()
    raw.pop("model_mode")
    path = tmp_path / "old-calibration.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    loaded = GazeModel.load(path)
    assert loaded is not None
    assert loaded.metrics.validation_rmse == 0.0
    assert loaded.metrics.validation_points == 0
    assert loaded.error_rmse == loaded.metrics.loo_rmse


def test_hybrid_uses_kernel_stage_for_nonlinear_mapping() -> None:
    rng = np.random.default_rng(11)
    width, height = 1920, 1200
    samples: list[np.ndarray] = []
    targets: list[list[float]] = []
    point_ids: list[int] = []
    point = 0
    for y in np.linspace(height * 0.12, height * 0.88, 5):
        for x in np.linspace(width * 0.08, width * 0.92, 5):
            for _ in range(12):
                nx = x / width - 0.5
                ny = y / height - 0.5
                iris_x = 0.5 + 0.40 * np.tanh(2.0 * nx) + rng.normal(0, 0.003)
                iris_y = 0.5 + 0.40 * np.tanh(2.0 * ny) + rng.normal(0, 0.003)
                values = np.zeros(len(FEATURE_NAMES))
                values[0] = values[2] = values[4] = iris_x
                values[1] = values[3] = values[5] = iris_y
                values[8] = 0.08 * nx + rng.normal(0, 0.002)
                values[9] = 0.05 * ny + rng.normal(0, 0.002)
                values[10] = rng.normal(0, 0.002)
                values[11] = 0.06 * nx + rng.normal(0, 0.002)
                values[12] = 0.04 * ny + rng.normal(0, 0.002)
                values[13] = 0.5
                # A cubic term is deliberately outside the polynomial basis.
                target_x = width * (
                    0.5 + 0.45 * (nx + 0.25 * nx**3) + 0.05 * values[8]
                )
                target_y = height * (
                    0.5 + 0.45 * (ny + 0.25 * ny**3) + 0.05 * values[9]
                )
                samples.append(values)
                targets.append([target_x, target_y])
                point_ids.append(point)
            point += 1

    model = GazeModel.fit(
        np.asarray(samples),
        np.asarray(targets),
        np.asarray(point_ids, dtype=np.int64),
        0.12,
        SCREEN.to_dict(),
    )
    assert model.metrics.krr_weight > 0.0
    assert model.metrics.loo_rmse < 40.0


def test_mouse_correction_moves_prediction_and_persists(tmp_path) -> None:
    samples, targets, point_ids = make_dataset()
    model = GazeModel.fit(samples, targets, point_ids, 0.12, SCREEN.to_dict())
    feature = samples[100].copy()
    before = model.predict(feature)
    target = (before.x + 180.0, before.y - 120.0)

    corrected = model.with_correction(feature, target)
    after = corrected.predict(feature)
    assert corrected.metrics.corrections == 1
    assert len(corrected.correction_features) == 1
    assert abs(after.x - target[0]) < 2.0
    assert abs(after.y - target[1]) < 2.0

    # A correction in the same feature region replaces the old one instead of
    # compounding into an overshoot.
    target2 = (target[0] - 60.0, target[1] + 30.0)
    corrected2 = corrected.with_correction(feature, target2)
    after2 = corrected2.predict(feature)
    assert corrected2.metrics.corrections == 2
    assert len(corrected2.correction_features) == 1
    assert abs(after2.x - target2[0]) < 2.0
    assert abs(after2.y - target2[1]) < 2.0

    path = tmp_path / "corrected.json"
    corrected2.save(path)
    loaded = GazeModel.load(path)
    assert loaded is not None
    assert loaded.metrics.corrections == 2
    assert len(loaded.correction_features) == 1
    restored = loaded.predict(feature)
    assert abs(restored.x - target2[0]) < 2.0
    assert abs(restored.y - target2[1]) < 2.0


def test_save_and_load_roundtrip(tmp_path) -> None:
    samples, targets, point_ids = make_dataset()
    model = GazeModel.fit(
        samples,
        targets,
        point_ids,
        0.12,
        SCREEN.to_dict(),
        validation_rmse=37.0,
        validation_points=9,
    )
    path = tmp_path / "calibration.json"
    model.save(path)
    loaded = GazeModel.load(path)
    assert loaded is not None
    assert loaded.metrics.n_points == model.metrics.n_points
    assert loaded.metrics.validation_rmse == 37.0
    assert loaded.metrics.validation_points == 9
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
