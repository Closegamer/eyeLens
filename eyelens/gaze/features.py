"""Convert MediaPipe face landmarks into scale-invariant eye/head features.

The feature vector mixes eye-in-head information (iris position inside each
eye) with head-pose proxies.  A per-user calibration learns the mapping from
these features to screen coordinates, which is considerably more robust than
using raw iris pixels alone.

All eye-local measurements are made in a rotated eye frame.  This matters:
normalising the iris by the raw eyelid height makes vertical gaze depend on how
open the eye happens to be, and makes both vertical gaze and blink detection
change when the head tilts.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# MediaPipe FaceMesh landmark indices (478-point model with irises).
RIGHT_EYE_OUTER = 33
RIGHT_EYE_INNER = 133
RIGHT_EYE_UPPER = 159
RIGHT_EYE_LOWER = 145
RIGHT_IRIS_CENTER = 468

LEFT_EYE_INNER = 362
LEFT_EYE_OUTER = 263
LEFT_EYE_UPPER = 386
LEFT_EYE_LOWER = 374
LEFT_IRIS_CENTER = 473

NOSE_TIP = 1
FACE_LEFT = 234
FACE_RIGHT = 454

# Bump when the meaning or order of features changes.  Saved calibrations with
# an older version are rejected and the user is asked to calibrate again.
FEATURE_VERSION = 2

FEATURE_NAMES: tuple[str, ...] = (
    "iris_rx",
    "iris_ry",
    "iris_lx",
    "iris_ly",
    "iris_x",
    "iris_y",
    "iris_dx",
    "iris_dy",
    "head_yaw",
    "head_pitch",
    "head_roll",
    "face_x",
    "face_y",
    "face_size",
)

# Curated second-order terms.  A full quadratic expansion in 14 dimensions
# would have 119 terms; these interactions capture the effects that matter
# without exploding the model.  The KRR residual model in gaze/model.py adds
# the remaining local nonlinearity.
_SQUARED = (
    "iris_rx",
    "iris_ry",
    "iris_lx",
    "iris_ly",
    "iris_x",
    "iris_y",
    "iris_dx",
    "iris_dy",
    "head_yaw",
    "head_pitch",
    "head_roll",
    "face_x",
    "face_y",
    "face_size",
)
_CROSS = (
    ("iris_x", "head_yaw"),
    ("iris_x", "head_pitch"),
    ("iris_x", "head_roll"),
    ("iris_x", "face_x"),
    ("iris_x", "face_y"),
    ("iris_x", "face_size"),
    ("iris_y", "head_yaw"),
    ("iris_y", "head_pitch"),
    ("iris_y", "head_roll"),
    ("iris_y", "face_x"),
    ("iris_y", "face_y"),
    ("iris_y", "face_size"),
    ("iris_x", "iris_y"),
    ("iris_dx", "iris_dy"),
    ("head_yaw", "head_pitch"),
    ("head_yaw", "head_roll"),
    ("head_pitch", "head_roll"),
    ("head_yaw", "face_x"),
    ("head_pitch", "face_y"),
    ("face_x", "face_y"),
    ("face_x", "face_size"),
    ("face_y", "face_size"),
    ("iris_x", "iris_dx"),
    ("iris_y", "iris_dy"),
)

EXPANDED_FEATURE_NAMES: tuple[str, ...] = (
    FEATURE_NAMES
    + tuple(f"{name}^2" for name in _SQUARED)
    + tuple(f"{a}*{b}" for a, b in _CROSS)
)

_NAME_TO_INDEX = {name: i for i, name in enumerate(FEATURE_NAMES)}


@dataclass(frozen=True)
class EyeFeatures:
    values: np.ndarray
    openness: float
    #: 1.0 when both eyes are comfortably open, < 1 as they close.
    quality: float = 1.0


def _point(points: np.ndarray, index: int) -> np.ndarray:
    return points[index]


def _eye_geometry(
    points: np.ndarray,
    corner_a: int,
    corner_b: int,
    upper: int,
    lower: int,
    iris: int,
) -> tuple[float, float, float]:
    """Return (iris_x, iris_y, openness) in a roll-tolerant eye frame.

    ``iris_x`` is the iris position along the corner-to-corner axis (0 at one
    canthus, 1 at the other).  ``iris_y`` is the perpendicular offset from that
    axis in units of eye width, positive downwards.  Both are independent of
    head tilt.  ``openness`` is the perpendicular eyelid gap divided by eye
    width, so it is also tilt-independent.
    """
    a = _point(points, corner_a)
    b = _point(points, corner_b)
    if a[0] > b[0]:
        a, b = b, a

    axis = b - a
    width = float(np.linalg.norm(axis))
    if width < 1e-3:
        raise ValueError("degenerate eye")
    u = axis / width
    # Rotate u by +90 degrees: with y pointing down this is the "down" axis.
    v = np.array([-u[1], u[0]], dtype=np.float64)

    iris_point = _point(points, iris)
    iris_offset = iris_point - a
    iris_x = float(np.dot(iris_offset, u) / width)
    iris_y = float(np.dot(iris_offset, v) / width)

    top = _point(points, upper)
    bottom = _point(points, lower)
    top_s = float(np.dot(top - a, v))
    bottom_s = float(np.dot(bottom - a, v))
    if top_s > bottom_s:
        top_s, bottom_s = bottom_s, top_s
    lid_gap = bottom_s - top_s
    openness = float(np.clip(lid_gap / width, 0.0, 1.0))

    return (
        float(np.clip(iris_x, -0.35, 1.35)),
        float(np.clip(iris_y, -1.5, 1.5)),
        openness,
    )


def _clip_feature(value: float, low: float, high: float) -> float:
    return float(np.clip(value, low, high))


def extract_features(
    landmarks: object, frame_width: int, frame_height: int
) -> EyeFeatures | None:
    """Extract :class:`EyeFeatures` from MediaPipe normalized landmarks."""
    try:
        points = np.array(
            [(lm.x * frame_width, lm.y * frame_height) for lm in landmarks],
            dtype=np.float64,
        )
    except (AttributeError, TypeError, ValueError):
        return None
    if points.ndim != 2 or points.shape[0] <= LEFT_IRIS_CENTER or points.shape[1] < 2:
        return None
    if not np.all(np.isfinite(points)):
        return None

    try:
        r_x, r_y, r_open = _eye_geometry(
            points,
            RIGHT_EYE_OUTER,
            RIGHT_EYE_INNER,
            RIGHT_EYE_UPPER,
            RIGHT_EYE_LOWER,
            RIGHT_IRIS_CENTER,
        )
        l_x, l_y, l_open = _eye_geometry(
            points,
            LEFT_EYE_OUTER,
            LEFT_EYE_INNER,
            LEFT_EYE_UPPER,
            LEFT_EYE_LOWER,
            LEFT_IRIS_CENTER,
        )
        right_center = (
            points[RIGHT_EYE_OUTER, :2] + points[RIGHT_EYE_INNER, :2]
        ) * 0.5
        left_center = (
            points[LEFT_EYE_OUTER, :2] + points[LEFT_EYE_INNER, :2]
        ) * 0.5
        if right_center[0] > left_center[0]:
            right_center, left_center = left_center, right_center

        iod = float(np.linalg.norm(right_center - left_center))
        if iod < 1e-3:
            return None
        eye_mid = (right_center + left_center) * 0.5
        nose = points[NOSE_TIP, :2]
        face_width = float(
            np.linalg.norm(points[FACE_LEFT, :2] - points[FACE_RIGHT, :2])
        )
        # Eye axis from image-left to image-right, so a level head is near 0
        # rather than near pi (and never gets clamped to a constant).
        eye_axis = left_center - right_center
        roll = float(np.arctan2(eye_axis[1], eye_axis[0]))
        # Apparent face size is a distance proxy.  face_width / iod is almost
        # constant for a given person and therefore useless for depth.
        face_size = face_width / max(float(frame_width), 1.0)

        values = np.array(
            [
                _clip_feature(r_x, -0.35, 1.35),
                _clip_feature(r_y, -1.5, 1.5),
                _clip_feature(l_x, -0.35, 1.35),
                _clip_feature(l_y, -1.5, 1.5),
                _clip_feature((r_x + l_x) * 0.5, -0.35, 1.35),
                _clip_feature((r_y + l_y) * 0.5, -1.5, 1.5),
                _clip_feature(l_x - r_x, -1.5, 1.5),
                _clip_feature(l_y - r_y, -1.5, 1.5),
                _clip_feature((nose[0] - eye_mid[0]) / iod, -1.5, 1.5),
                _clip_feature((nose[1] - eye_mid[1]) / iod, -1.5, 2.0),
                _clip_feature(roll, -0.8, 0.8),
                _clip_feature((eye_mid[0] - frame_width * 0.5) / iod, -6.0, 6.0),
                _clip_feature((eye_mid[1] - frame_height * 0.5) / iod, -6.0, 6.0),
                _clip_feature(face_size, 0.02, 4.0),
            ],
            dtype=np.float64,
        )
    except (IndexError, ValueError):
        return None

    if not np.all(np.isfinite(values)):
        return None

    openness = max(0.0, min(1.0, (r_open + l_open) * 0.5))
    quality = float(np.clip(openness / 0.22, 0.0, 1.0))
    return EyeFeatures(values=values, openness=openness, quality=quality)


def expand_features(values: np.ndarray) -> np.ndarray:
    """Apply the fixed polynomial expansion used by the calibration model."""
    values = np.asarray(values, dtype=np.float64).reshape(-1)
    if values.size != len(FEATURE_NAMES):
        raise ValueError(
            f"expected {len(FEATURE_NAMES)} features, got {values.size}"
        )
    terms: list[float] = values.tolist()
    terms.extend(values[_NAME_TO_INDEX[name]] ** 2 for name in _SQUARED)
    terms.extend(
        values[_NAME_TO_INDEX[a]] * values[_NAME_TO_INDEX[b]] for a, b in _CROSS
    )
    return np.asarray(terms, dtype=np.float64)


def expand_matrix(matrix: np.ndarray) -> np.ndarray:
    """Vectorized :func:`expand_features` for a matrix of samples."""
    matrix = np.asarray(matrix, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] != len(FEATURE_NAMES):
        raise ValueError(
            f"expected N x {len(FEATURE_NAMES)} features, got {matrix.shape}"
        )
    columns = [matrix]
    columns.extend(
        (matrix[:, _NAME_TO_INDEX[name]] ** 2)[:, None] for name in _SQUARED
    )
    columns.extend(
        (
            matrix[:, _NAME_TO_INDEX[a]] * matrix[:, _NAME_TO_INDEX[b]]
        )[:, None]
        for a, b in _CROSS
    )
    return np.concatenate(columns, axis=1)
