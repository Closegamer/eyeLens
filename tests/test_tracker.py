from __future__ import annotations

import time

import numpy as np
import pytest

from eyelens.gaze.features import FEATURE_NAMES
from eyelens.gaze.tracker import (
    EYE_PREVIEW_HEIGHT,
    EYE_PREVIEW_WIDTH,
    EyeTracker,
    TrackerSnapshot,
    eye_crop_box,
)


def _snapshot(
    seq: int,
    timestamp: float,
    values: np.ndarray | None,
    openness: float = 0.3,
    head_pose: np.ndarray | None = None,
) -> TrackerSnapshot:
    return TrackerSnapshot(
        seq=seq,
        features=values,
        openness=openness,
        face_found=values is not None,
        timestamp=timestamp,
        fps=30.0,
        head_pose=head_pose,
    )


def test_recent_features_returns_median_of_open_frames() -> None:
    tracker = EyeTracker(None)
    now = time.monotonic()
    for index in range(10):
        values = np.zeros(len(FEATURE_NAMES))
        values[0] = 0.4 + 0.02 * index
        tracker._history.append(
            _snapshot(index, now - 0.5 + 0.05 * index, values)
        )
    result = tracker.recent_features(seconds=1.0)
    assert result is not None
    assert result.shape == (len(FEATURE_NAMES),)
    assert 0.44 < result[0] < 0.50


def test_recent_features_rejects_blinks_and_missing_face() -> None:
    tracker = EyeTracker(None)
    now = time.monotonic()
    values = np.zeros(len(FEATURE_NAMES))
    for index in range(6):
        tracker._history.append(
            _snapshot(index, now - 0.2 + 0.01 * index, values, openness=0.01)
        )
    assert tracker.recent_features(seconds=1.0) is None

    tracker._history.clear()
    for index in range(6):
        tracker._history.append(_snapshot(index, now - 0.2, None))
    assert tracker.recent_features(seconds=1.0) is None


def test_recent_head_pose_returns_median() -> None:
    tracker = EyeTracker(None)
    now = time.monotonic()
    values = np.zeros(len(FEATURE_NAMES))
    poses = [
        np.array([0.1 * index, 0.0, 1.0, 10.0, 20.0, -60.0])
        for index in range(5)
    ]
    for index, pose in enumerate(poses):
        tracker._history.append(
            _snapshot(
                index,
                now - 0.2 + 0.01 * index,
                values,
                head_pose=pose,
            )
        )
    result = tracker.recent_head_pose(seconds=1.0)
    assert result is not None
    assert np.allclose(result, np.median(np.vstack(poses), axis=0))
    tracker._history.clear()
    tracker._history.append(_snapshot(0, now, values))
    assert tracker.recent_head_pose(seconds=1.0) is None


def test_eye_crop_box_is_zoomed_and_inside_the_frame() -> None:
    points = np.asarray(
        [
            [200, 150],
            [260, 145],
            [320, 160],
            [380, 148],
            [440, 155],
            [200, 210],
            [440, 215],
        ],
        dtype=np.float64,
    )
    box = eye_crop_box(points, 640, 480)
    assert box is not None
    x0, y0, x1, y1 = box
    assert 0 <= x0 < x1 <= 640
    assert 0 <= y0 < y1 <= 480
    assert (x1 - x0) >= 160
    assert (x1 - x0) / (y1 - y0) == pytest.approx(
        EYE_PREVIEW_WIDTH / EYE_PREVIEW_HEIGHT, rel=0.03
    )
    assert x0 <= 200 and x1 >= 440
    assert y0 <= 145 and y1 >= 215

    edge_box = eye_crop_box(points - 190.0, 640, 480)
    assert edge_box is not None
    ex0, ey0, ex1, ey1 = edge_box
    assert 0 <= ex0 < ex1 <= 640
    assert 0 <= ey0 < ey1 <= 480
    assert eye_crop_box(np.zeros((0, 2)), 640, 480) is None
