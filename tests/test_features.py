from __future__ import annotations

import math

import numpy as np

from eyelens.gaze.features import (
    EXPANDED_FEATURE_NAMES,
    FEATURE_NAMES,
    LEFT_EYE_INNER,
    LEFT_EYE_LOWER,
    LEFT_EYE_OUTER,
    LEFT_EYE_UPPER,
    LEFT_IRIS_CENTER,
    NOSE_TIP,
    RIGHT_EYE_INNER,
    RIGHT_EYE_LOWER,
    RIGHT_EYE_OUTER,
    RIGHT_EYE_UPPER,
    RIGHT_IRIS_CENTER,
    expand_features,
    extract_features,
    extract_head_pose,
)

FRAME_W = 640
FRAME_H = 480


class LM:
    __slots__ = ("x", "y", "z")

    def __init__(self, x: float, y: float, z: float = 0.0) -> None:
        self.x = x
        self.y = y
        self.z = z


def make_landmarks(
    iris_dx: float = 0.0,
    iris_dy: float = 0.0,
    closed: bool = False,
    head_dx: float = 0.0,
) -> list[LM]:
    points = [LM(0.5, 0.5) for _ in range(478)]
    points[RIGHT_EYE_OUTER] = LM(0.30 + head_dx, 0.46)
    points[RIGHT_EYE_INNER] = LM(0.42 + head_dx, 0.46)
    points[RIGHT_EYE_UPPER] = LM(0.36 + head_dx, 0.47 if closed else 0.44)
    points[RIGHT_EYE_LOWER] = LM(0.36 + head_dx, 0.47 if closed else 0.50)
    points[RIGHT_IRIS_CENTER] = LM(0.36 + head_dx + iris_dx, 0.47 + iris_dy)

    points[LEFT_EYE_INNER] = LM(0.58 + head_dx, 0.46)
    points[LEFT_EYE_OUTER] = LM(0.70 + head_dx, 0.46)
    points[LEFT_EYE_UPPER] = LM(0.64 + head_dx, 0.47 if closed else 0.44)
    points[LEFT_EYE_LOWER] = LM(0.64 + head_dx, 0.47 if closed else 0.50)
    points[LEFT_IRIS_CENTER] = LM(0.64 + head_dx + iris_dx, 0.47 + iris_dy)

    points[NOSE_TIP] = LM(0.5 + head_dx, 0.58)
    points[234] = LM(0.25 + head_dx, 0.5)
    points[454] = LM(0.75 + head_dx, 0.5)
    return points


def test_feature_shape_and_finiteness() -> None:
    features = extract_features(make_landmarks(), FRAME_W, FRAME_H)
    assert features is not None
    assert features.values.shape == (len(FEATURE_NAMES),)
    assert np.all(np.isfinite(features.values))
    assert 0.2 < features.openness < 0.6


def test_iris_moves_consistently_in_both_eyes() -> None:
    center = extract_features(make_landmarks(), FRAME_W, FRAME_H)
    right = extract_features(make_landmarks(iris_dx=0.02), FRAME_W, FRAME_H)
    assert center is not None and right is not None
    assert right.values[0] > center.values[0]  # right eye ratio
    assert right.values[2] > center.values[2]  # left eye ratio
    assert right.values[4] > center.values[4]  # averaged signal
    assert abs(right.values[6] - center.values[6]) < 0.02  # vergence stays flat


def test_closed_eyes_reduce_openness() -> None:
    open_eye = extract_features(make_landmarks(), FRAME_W, FRAME_H)
    closed = extract_features(make_landmarks(closed=True), FRAME_W, FRAME_H)
    assert open_eye is not None and closed is not None
    assert closed.openness < 0.12
    assert closed.openness < open_eye.openness


def test_head_translation_changes_face_features() -> None:
    centered = extract_features(make_landmarks(), FRAME_W, FRAME_H)
    shifted = extract_features(make_landmarks(head_dx=0.03), FRAME_W, FRAME_H)
    assert centered is not None and shifted is not None
    assert shifted.values[11] > centered.values[11]


def test_eye_features_are_roll_invariant() -> None:
    """Tilting the head must not change vertical iris position or openness."""

    def rotated(angle: float) -> list[LM]:
        points = make_landmarks(iris_dy=-0.01)
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        result = []
        for point in points:
            dx = point.x - 0.5
            dy = point.y - 0.5
            result.append(
                LM(
                    0.5 + dx * cos_a - dy * sin_a,
                    0.5 + dx * sin_a + dy * cos_a,
                    point.z,
                )
            )
        return result

    level = extract_features(rotated(0.0), FRAME_W, FRAME_H)
    tilted = extract_features(rotated(0.18), FRAME_W, FRAME_H)
    assert level is not None and tilted is not None
    assert abs(level.values[4] - tilted.values[4]) < 0.02
    assert abs(level.values[5] - tilted.values[5]) < 0.02
    assert abs(level.openness - tilted.openness) < 0.02
    assert abs(level.values[10] - tilted.values[10]) > 0.10


def test_expanded_feature_length() -> None:
    features = extract_features(make_landmarks(), FRAME_W, FRAME_H)
    assert features is not None
    expanded = expand_features(features.values)
    assert expanded.shape == (len(EXPANDED_FEATURE_NAMES),)
    assert np.all(np.isfinite(expanded))


def test_extract_head_pose() -> None:
    matrix = np.eye(4)
    matrix[:3, 3] = [10.0, 20.0, -60.0]
    pose = extract_head_pose(matrix)
    assert pose is not None
    assert pose.shape == (6,)
    assert np.allclose(pose, [0.0, 0.0, 1.0, 10.0, 20.0, -60.0])
    assert extract_head_pose(None) is None
    assert extract_head_pose(np.zeros((3, 3))) is None
