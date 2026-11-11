"""Full-screen, guided eye-tracking calibration."""

from __future__ import annotations

import contextlib
import ctypes
import math
import platform
import time
from enum import Enum, auto

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from ..gaze.features import (
    DEFAULT_CONTROL_MODE,
    FEATURE_NAMES,
    normalized_control_mode,
)
from ..gaze.model import POSE_ALPHAS, GazeModel, fit_pose_correction
from ..gaze.tracker import EyeTracker
from .overlay import screen_info

BRAND = QColor("#38bdf8")
BRAND_SOFT = QColor("#7dd3fc")
TEXT = QColor("#e8f2ff")
MUTED = QColor("#8fa3ba")
GREEN = QColor("#34d399")
RED = QColor("#f87171")
AMBER = QColor("#fbbf24")


class Phase(Enum):
    INTRO = auto()
    COUNTDOWN = auto()
    SETTLE = auto()
    SAMPLE = auto()
    RETRY = auto()
    FIT = auto()
    RESULT = auto()
    ERROR = auto()


class CalibrationWindow(QWidget):
    finished = Signal(object)  # GazeModel
    cancelled = Signal()

    GRID_X = (0.05, 0.275, 0.5, 0.725, 0.95)
    GRID_Y_TOP = 0.20
    GRID_Y_BOTTOM = 0.90
    # Head control needs training targets near the real borders so the model
    # can predict the taskbar and screen corners.  Eye control keeps the more
    # conservative interior grid, where iris landmarks are reliable.
    HEAD_GRID_X = (0.03, 0.265, 0.5, 0.735, 0.97)
    HEAD_GRID_Y_TOP = 0.10
    HEAD_GRID_Y_BOTTOM = 0.96
    PREVIEW_RECT = QRectF(24, 24, 320, 150)
    FACE_PILL_RECT = QRectF(24, 184, 260, 28)
    VALIDATION_GRID_X = (0.16, 0.5, 0.84)
    VALIDATION_GRID_Y = (0.28, 0.55, 0.82)
    SETTLE_SECONDS = 0.65
    STABLE_SECONDS = 0.65
    MOTION_SECONDS = 1.00
    SAMPLE_SECONDS = STABLE_SECONDS + MOTION_SECONDS
    # Head aiming needs no head-motion sub-window: the user moves their head
    # between dots and holds still on each target.  Shorter sampling keeps the
    # whole head calibration around 45 seconds.
    HEAD_SETTLE_SECONDS = 0.55
    HEAD_SAMPLE_SECONDS = 0.95
    RETRY_SECONDS = 1.50
    COUNTDOWN_SECONDS = 2.0

    def __init__(
        self,
        tracker: EyeTracker,
        screen,
        parent=None,
        control_mode: str = DEFAULT_CONTROL_MODE,
    ) -> None:
        super().__init__(parent)
        self.tracker = tracker
        self.screen = screen
        self.control_mode = normalized_control_mode(control_mode)
        self._head_control = self.control_mode == "head"
        if self._head_control:
            self._settle_seconds = self.HEAD_SETTLE_SECONDS
            self._sample_seconds = self.HEAD_SAMPLE_SECONDS
            self._stable_seconds = self.HEAD_SAMPLE_SECONDS
        else:
            self._settle_seconds = self.SETTLE_SECONDS
            self._sample_seconds = self.SAMPLE_SECONDS
            self._stable_seconds = self.STABLE_SECONDS
        self.setWindowTitle("eyeLens head calibration")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(False)
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.setGeometry(screen.geometry())
        self.setScreen(screen)

        self._phase = Phase.INTRO
        self._phase_started = time.monotonic()
        self._point_index = 0
        self._retried = False
        self._retry_reason = ""
        self._current_samples: list[
            tuple[np.ndarray, float, np.ndarray | None]
        ] = []
        self._current_motion_samples: list[
            tuple[np.ndarray, float, np.ndarray | None]
        ] = []
        self._samples: list[np.ndarray] = []
        self._targets: list[list[float]] = []
        self._point_id_list: list[int] = []
        self._pose_list: list[np.ndarray | None] = []
        self._motion_samples: list[np.ndarray] = []
        self._motion_targets: list[list[float]] = []
        self._motion_point_ids: list[int] = []
        self._motion_poses: list[np.ndarray] = []
        self._all_openness: list[float] = []
        self._last_seq = -1
        self._face_found = False
        self._face_since: float | None = None
        self._preview: QImage | None = None
        self._eye_preview: QImage | None = None
        self._model: GazeModel | None = None
        self._primary_model: GazeModel | None = None
        self._head_baseline: np.ndarray | None = None
        self._head_warning = False
        self._motion_hint = False
        self._error_message = ""
        self._done = False
        self._fit_started = False
        self._fit_stage = "primary"
        self._validating = False
        self._validation_start = 0
        self._countdown_seconds = self.COUNTDOWN_SECONDS
        self._countdown_note = (
            "Get comfortable and keep your face in view"
            if self._head_control
            else "Get comfortable and keep looking at the screen"
        )
        self._primary_points = self._build_points()
        self._validation_points = self._build_validation_points()
        self._points = self._primary_points

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ---------------------------------------------------------------- geometry
    @staticmethod
    def _center_out(
        points: list[tuple[float, float]],
    ) -> list[tuple[float, float]]:
        """Centre first, then expanding rings.

        A predictable spatial order is much easier for the user to follow than
        a random jump across the screen.  Randomising the order made gaze
        sampling noticeably worse; slow head drift is handled by the head
        warning and the optional pose correction instead.
        """
        if not points:
            return points
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        center_x = (min(xs) + max(xs)) * 0.5
        center_y = (min(ys) + max(ys)) * 0.5
        scale_x = max(max(xs) - min(xs), 1.0)
        scale_y = max(max(ys) - min(ys), 1.0)

        def key(point: tuple[float, float]) -> tuple[float, float]:
            dx = (point[0] - center_x) / scale_x
            dy = (point[1] - center_y) / scale_y
            return (round(dx * dx + dy * dy, 6), math.atan2(dy, dx))

        return sorted(points, key=key)

    def _build_points(self) -> list[tuple[float, float]]:
        geometry = self.screen.geometry()
        width = float(geometry.width())
        height = float(geometry.height())
        if self._head_control:
            top_y = height * self.HEAD_GRID_Y_TOP
            bottom_y = height * self.HEAD_GRID_Y_BOTTOM
            xs = [
                geometry.left() + width * frac for frac in self.HEAD_GRID_X
            ]
        else:
            top_y = max(height * self.GRID_Y_TOP, 230.0)
            bottom_y = height * self.GRID_Y_BOTTOM
            xs = [geometry.left() + width * frac for frac in self.GRID_X]
        ys = [
            geometry.top() + top_y + (bottom_y - top_y) * index / 4.0
            for index in range(5)
        ]
        return self._center_out([(x, y) for y in ys for x in xs])

    def _build_validation_points(self) -> list[tuple[float, float]]:
        geometry = self.screen.geometry()
        width = float(geometry.width())
        height = float(geometry.height())
        top_y = max(height * self.GRID_Y_TOP, 230.0)
        bottom_y = height * self.GRID_Y_BOTTOM
        xs = [
            geometry.left() + width * frac for frac in self.VALIDATION_GRID_X
        ]
        ys = [
            geometry.top() + top_y + (bottom_y - top_y) * frac
            for frac in self.VALIDATION_GRID_Y
        ]
        return self._center_out([(x, y) for y in ys for x in xs])

    # --------------------------------------------------------------- lifecycle
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.setGeometry(self.screen.geometry())
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        self.tracker.acquire_preview()
        self._prevent_sleep(True)
        self._phase_started = time.monotonic()
        self.update()

    def closeEvent(self, event) -> None:
        self._timer.stop()
        self._prevent_sleep(False)
        with contextlib.suppress(Exception):
            self.tracker.release_preview()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        if not self._done:
            self._done = True
            self.cancelled.emit()
        super().closeEvent(event)

    def _prevent_sleep(self, enabled: bool) -> None:
        if platform.system() != "Windows":
            return
        try:
            es_continuous = 0x80000000
            es_display_required = 0x00000002
            flags = es_continuous | (es_display_required if enabled else 0)
            ctypes.windll.kernel32.SetThreadExecutionState(flags)
        except Exception:
            pass

    # ------------------------------------------------------------------ input
    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._cancel()
            return
        if self._phase == Phase.INTRO and key in (
            Qt.Key.Key_Space,
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            if self._face_found:
                self._begin_countdown()
            return
        if self._phase == Phase.RESULT:
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                if self._model is not None and self._model.quality_ok:
                    self._accept()
                return
            if key == Qt.Key.Key_R:
                self._restart_all()
                return
        if self._phase == Phase.ERROR and key == Qt.Key.Key_R:
            self._restart_all()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if self._phase == Phase.INTRO and self._face_found:
            self._begin_countdown()
        super().mousePressEvent(event)

    def _cancel(self) -> None:
        if self._done:
            return
        self._done = True
        self.cancelled.emit()
        self.close()

    def _accept(self) -> None:
        if (
            self._model is None
            or self._done
            or not self._model.quality_ok
        ):
            return
        self._done = True
        self.finished.emit(self._model)
        self.close()

    # ------------------------------------------------------------------- phases
    def _enter(self, phase: Phase) -> None:
        self._phase = phase
        self._phase_started = time.monotonic()
        self.update()

    def _begin_countdown(self) -> None:
        self._phase_started = time.monotonic()
        self._enter(Phase.COUNTDOWN)

    def _restart_all(self) -> None:
        self._point_index = 0
        self._retried = False
        self._retry_reason = ""
        self._current_samples = []
        self._current_motion_samples = []
        self._samples = []
        self._targets = []
        self._point_id_list = []
        self._pose_list = []
        self._motion_samples = []
        self._motion_targets = []
        self._motion_point_ids = []
        self._motion_poses = []
        self._all_openness = []
        self._model = None
        self._primary_model = None
        self._head_baseline = None
        self._head_warning = False
        self._error_message = ""
        self._fit_started = False
        self._fit_stage = "primary"
        self._validating = False
        self._validation_start = 0
        self._countdown_seconds = self.COUNTDOWN_SECONDS
        self._countdown_note = (
            "Get comfortable and keep your face in view"
            if self._head_control
            else "Get comfortable and keep looking at the screen"
        )
        self._points = self._primary_points
        self._begin_countdown()

    def _start_point(self) -> None:
        self._current_samples = []
        self._current_motion_samples = []
        self._last_seq = -1
        self._motion_hint = False
        self._enter(Phase.SETTLE)

    def _start_sampling(self) -> None:
        self._enter(Phase.SAMPLE)

    def _start_validation(self, primary: GazeModel) -> None:
        self._primary_model = primary
        self._validating = True
        self._points = self._validation_points
        self._point_index = 0
        self._retried = False
        self._retry_reason = ""
        self._current_samples = []
        self._current_motion_samples = []
        self._last_seq = -1
        self._validation_start = len(self._samples)
        self._fit_started = False
        self._fit_stage = "final"
        self._countdown_seconds = 1.5
        self._countdown_note = (
            "Accuracy check — aim your head at each dot"
            if self._head_control
            else "Accuracy check — keep looking at the screen"
        )
        self._begin_countdown()

    def _finish_point(self) -> None:
        filtered = self._filter_current_samples()
        accepted = filtered[0] if filtered is not None else None
        poses = filtered[1] if filtered is not None else None
        if accepted is None or accepted.shape[0] < 6:
            if not self._retried:
                self._retried = True
                if self._head_warning:
                    self._retry_reason = (
                        "Head moved — return to your starting head position "
                        "and keep still. Trying this point again…"
                    )
                else:
                    self._retry_reason = (
                        "Hold still — I lost your face. Trying this point again…"
                        if accepted is None
                        else "Not enough steady samples. Trying this point again…"
                    )
                self._enter(Phase.RETRY)
            else:
                self._error_message = (
                    "Head tracking was not stable enough. Improve the lighting "
                    "and make sure your face is fully visible."
                    if self._head_control
                    else "Eye tracking was not stable enough. Improve the "
                    "lighting, keep your head still, and make sure your face is "
                    "fully visible."
                )
                self._enter(Phase.ERROR)
            return

        target = self._points[self._point_index]
        if (
            not self._head_control
            and not self._validating
            and self._point_index == 0
        ):
            # The first (centre) point defines the head position the user
            # should keep for the rest of the session.
            self._head_baseline = np.median(accepted[:, 8:14], axis=0)
        point_id = self._point_index + (
            len(self._primary_points) if self._validating else 0
        )
        if poses is not None and len(poses) != len(accepted):
            poses = None
        for index, row in enumerate(accepted):
            self._samples.append(row)
            self._targets.append([target[0], target[1]])
            self._point_id_list.append(point_id)
            self._pose_list.append(poses[index] if poses is not None else None)
        motion_filtered = (
            None if self._head_control else self._filter_motion_samples()
        )
        if motion_filtered is not None:
            motion_rows, motion_pose_matrix = motion_filtered
            if (
                motion_pose_matrix is not None
                and len(motion_pose_matrix) == len(motion_rows)
            ):
                for index, row in enumerate(motion_rows):
                    self._motion_samples.append(row)
                    self._motion_targets.append([target[0], target[1]])
                    self._motion_point_ids.append(point_id)
                    self._motion_poses.append(motion_pose_matrix[index])
        self._point_index += 1
        self._retried = False
        self._retry_reason = ""

        if self._point_index >= len(self._points):
            self._fit_started = False
            self._enter(Phase.FIT)
        else:
            self._start_point()

    def _validation_error(self, model: GazeModel) -> float:
        start = self._validation_start
        if start >= len(self._samples):
            return 0.0
        samples = self._samples[start:]
        targets = np.asarray(self._targets[start:], dtype=np.float64)
        point_ids = np.asarray(self._point_id_list[start:], dtype=np.int64)
        predictions = np.asarray(
            [
                [prediction.x, prediction.y]
                for prediction in (model.predict(row) for row in samples)
            ],
            dtype=np.float64,
        )
        per_point: dict[int, float] = {}
        for point in np.unique(point_ids):
            mask = point_ids == point
            error = predictions[mask] - targets[mask]
            per_point[int(point)] = float(np.mean(np.sum(np.square(error), axis=1)))
        if not per_point:
            return 0.0
        return float(np.sqrt(np.mean(list(per_point.values()))))

    @staticmethod
    def _point_rmse(
        predictions: np.ndarray,
        targets: np.ndarray,
        point_ids: np.ndarray,
    ) -> float:
        per_point: dict[int, float] = {}
        for point in np.unique(point_ids):
            mask = point_ids == point
            error = predictions[mask] - targets[mask]
            per_point[int(point)] = float(
                np.mean(np.sum(np.square(error), axis=1))
            )
        if not per_point:
            return 0.0
        return float(np.sqrt(np.mean(list(per_point.values()))))

    def _motion_arrays(
        self,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
        if not self._motion_samples or not self._motion_poses:
            return None
        samples = np.vstack(self._motion_samples)
        targets = np.asarray(self._motion_targets, dtype=np.float64)
        point_ids = np.asarray(self._motion_point_ids, dtype=np.int64)
        poses = np.asarray(self._motion_poses, dtype=np.float64)
        if (
            samples.shape[0] != targets.shape[0]
            or samples.shape[0] != point_ids.size
            or samples.shape[0] != poses.shape[0]
        ):
            return None
        return samples, targets, point_ids, poses

    def _select_pose_correction(
        self, primary: GazeModel
    ) -> tuple[float, float, float]:
        """Choose whether a global head-pose correction helps held-out points.

        The correction is fitted on the primary motion samples (same targets,
        deliberately varied head pose) and accepted only if it improves the
        combined stable+motion validation by at least 5% and 10 px.
        """
        base_stable = self._validation_error(primary)
        motion = self._motion_arrays()
        start = self._validation_start
        if (
            motion is None
            or start <= 0
            or start >= len(self._samples)
            or self._primary_model is None
            or any(pose is None for pose in self._pose_list)
        ):
            return base_stable, 0.0, 0.0
        (
            motion_samples,
            motion_targets,
            motion_ids,
            motion_poses,
        ) = motion
        primary_motion = motion_ids < len(self._primary_points)
        validation_motion = ~primary_motion
        if not np.any(primary_motion) or not np.any(validation_motion):
            return base_stable, 0.0, 0.0

        primary_motion_predictions = np.asarray(
            [
                [prediction.x, prediction.y]
                for prediction in (
                    primary.predict_unclipped(row)
                    for row in motion_samples[primary_motion]
                )
            ],
            dtype=np.float64,
        )
        motion_validation_predictions = np.asarray(
            [
                [prediction.x, prediction.y]
                for prediction in (
                    primary.predict_unclipped(row)
                    for row in motion_samples[validation_motion]
                )
            ],
            dtype=np.float64,
        )
        residuals = (
            motion_targets[primary_motion] - primary_motion_predictions
        )
        stable_validation_targets = np.asarray(
            self._targets[start:], dtype=np.float64
        )
        stable_validation_ids = np.asarray(
            self._point_id_list[start:], dtype=np.int64
        )
        stable_validation_poses = np.vstack(self._pose_list[start:])
        stable_validation_predictions = np.asarray(
            [
                [prediction.x, prediction.y]
                for prediction in (
                    primary.predict(row) for row in self._samples[start:]
                )
            ],
            dtype=np.float64,
        )
        motion_validation_targets = motion_targets[validation_motion]
        motion_validation_ids = motion_ids[validation_motion]
        motion_validation_poses = motion_poses[validation_motion]

        def combined_error(
            stable_predictions: np.ndarray,
            motion_predictions: np.ndarray,
        ) -> float:
            predictions = np.vstack(
                [stable_predictions, motion_predictions]
            )
            targets = np.vstack(
                [stable_validation_targets, motion_validation_targets]
            )
            ids = np.concatenate(
                [stable_validation_ids, motion_validation_ids]
            )
            return self._point_rmse(predictions, targets, ids)

        best_validation = combined_error(
            stable_validation_predictions, motion_validation_predictions
        )
        best_alpha = 0.0
        best_weight = 0.0
        for alpha in POSE_ALPHAS:
            correction = fit_pose_correction(
                motion_poses[primary_motion], residuals, float(alpha)
            )
            stable_corrected = stable_validation_predictions + np.asarray(
                [correction.apply(pose) for pose in stable_validation_poses],
                dtype=np.float64,
            )
            motion_corrected = motion_validation_predictions + np.asarray(
                [correction.apply(pose) for pose in motion_validation_poses],
                dtype=np.float64,
            )
            value = combined_error(stable_corrected, motion_corrected)
            if (
                value < best_validation * 0.95
                and best_validation - value >= 10.0
            ):
                best_validation = value
                best_alpha = float(alpha)
                best_weight = 1.0
        return best_validation, best_alpha, best_weight

    def _fit_model(self) -> None:
        if self._fit_started:
            return
        self._fit_started = True
        try:
            samples = np.vstack(self._samples)
            targets = np.asarray(self._targets, dtype=np.float64)
            point_ids = np.asarray(self._point_id_list, dtype=np.int64)
            openness = np.asarray(self._all_openness, dtype=np.float64)
            threshold = max(0.07, float(np.median(openness)) * 0.55)
            info = screen_info(self.screen).to_dict()

            if self._fit_stage == "primary":
                self._primary_model = GazeModel.fit(
                    samples=samples,
                    targets=targets,
                    point_ids=point_ids,
                    openness_threshold=threshold,
                    screen=info,
                    control_mode=self.control_mode,
                )
                self._start_validation(self._primary_model)
                return

            validation_rmse = 0.0
            pose_alpha = 0.0
            pose_weight = 0.0
            if self._primary_model is not None:
                if self._head_control:
                    validation_rmse = self._validation_error(self._primary_model)
                else:
                    (
                        validation_rmse,
                        pose_alpha,
                        pose_weight,
                    ) = self._select_pose_correction(self._primary_model)
            motion = None if self._head_control else self._motion_arrays()
            motion_samples = None
            motion_targets = None
            motion_point_ids = None
            motion_poses = None
            if pose_weight > 0 and motion is not None:
                (
                    motion_samples,
                    motion_targets,
                    motion_point_ids,
                    motion_poses,
                ) = motion
            self._model = GazeModel.fit(
                samples=samples,
                targets=targets,
                point_ids=point_ids,
                openness_threshold=threshold,
                screen=info,
                validation_rmse=validation_rmse,
                validation_points=len(self._validation_points),
                motion_samples=motion_samples,
                motion_targets=motion_targets,
                motion_point_ids=motion_point_ids,
                motion_poses=motion_poses,
                pose_alpha=pose_alpha,
                pose_weight=pose_weight,
                control_mode=self.control_mode,
            )
            # Keep all dots visible and completed on the result screen.
            self._points = self._primary_points + self._validation_points
            self._point_index = len(self._points)
            self._enter(Phase.RESULT)
        except (ValueError, IndexError) as exc:
            self._error_message = f"Could not build the calibration model: {exc}"
            self._enter(Phase.ERROR)

    def _filter_samples(
        self,
        entries: list[tuple[np.ndarray, float, np.ndarray | None]],
        filter_head: bool,
        use_openness: bool = True,
    ) -> tuple[np.ndarray, np.ndarray | None] | None:
        if len(entries) < 7:
            return None
        openness = np.array([item[1] for item in entries])
        median_open = float(np.median(openness))
        threshold = max(0.055, median_open * 0.55)
        filtered = [
            (features, pose)
            for features, value, pose in entries
            if not use_openness or value >= threshold
        ]
        if len(filtered) < 6:
            return None
        matrix = np.vstack([entry[0] for entry in filtered])
        poses = [entry[1] for entry in filtered]

        def apply_keep(keep: np.ndarray) -> None:
            nonlocal matrix, poses
            matrix = matrix[keep]
            poses = [pose for pose, keep_row in zip(poses, keep) if keep_row]

        median = np.median(matrix, axis=0)
        mad = np.median(np.abs(matrix - median), axis=0) * 1.4826
        valid_dims = mad > 1e-6
        if self._head_control:
            # Only the head/face features drive the model; eye movement and
            # blinks must not reject otherwise good head samples.
            valid_dims &= np.arange(matrix.shape[1]) >= 8
        elif not filter_head:
            # Head movement is intentional in the motion window; only reject
            # eye-feature outliers there.
            valid_dims &= np.arange(matrix.shape[1]) < 8
        z_limit = 4.25 if filter_head else 6.0
        refine_limit = 4.0 if filter_head else 5.5
        if np.any(valid_dims):
            deviation = np.abs(matrix[:, valid_dims] - median[valid_dims])
            z = deviation / mad[valid_dims]
            apply_keep(np.max(z, axis=1) <= z_limit)
            if matrix.shape[0] > 2:
                median = np.median(matrix, axis=0)
                mad = np.median(np.abs(matrix - median), axis=0) * 1.4826
                valid_dims = mad > 1e-6
                if self._head_control:
                    valid_dims &= np.arange(matrix.shape[1]) >= 8
                elif not filter_head:
                    valid_dims &= np.arange(matrix.shape[1]) < 8
                if np.any(valid_dims):
                    deviation = np.abs(
                        matrix[:, valid_dims] - median[valid_dims]
                    )
                    z = deviation / mad[valid_dims]
                    apply_keep(np.max(z, axis=1) <= refine_limit)
        if matrix.shape[0] < 6:
            return None
        pose_matrix = (
            None
            if any(pose is None for pose in poses)
            else np.vstack(poses)
        )
        return matrix, pose_matrix

    def _filter_current_samples(
        self,
    ) -> tuple[np.ndarray, np.ndarray | None] | None:
        return self._filter_samples(
            self._current_samples,
            filter_head=True,
            use_openness=not self._head_control,
        )

    def _filter_motion_samples(
        self,
    ) -> tuple[np.ndarray, np.ndarray | None] | None:
        return self._filter_samples(
            self._current_motion_samples, filter_head=False
        )

    # -------------------------------------------------------------------- timer
    def _tick(self) -> None:
        now = time.monotonic()
        snap = self.tracker.snapshot()
        face_before = self._face_found
        self._face_found = snap.face_found
        elapsed = now - self._phase_started
        warning_before = self._head_warning
        stable_for_warning = (
            not self._head_control
            and self._phase in (Phase.SETTLE, Phase.SAMPLE)
            and (
                self._phase != Phase.SAMPLE
                or elapsed < self._stable_seconds
            )
        )
        self._update_head_warning(
            snap.features
            if snap.face_found and stable_for_warning
            else None
        )
        if warning_before != self._head_warning:
            self.update(QRect(0, 60, int(self.width()), 34))
            self.update(QRect(0, int(self.height()) - 60, int(self.width()), 34))
        if snap.face_found:
            if self._face_since is None:
                self._face_since = now
        else:
            self._face_since = None

        if self.tracker.error_text and self._phase not in (Phase.ERROR, Phase.RESULT):
            self._error_message = self.tracker.error_text
            self._enter(Phase.ERROR)

        if (
            self._phase == Phase.INTRO
            and self._face_found
            and self._face_since is not None
            and now - self._face_since >= 0.9
        ):
            self._begin_countdown()
        elif self._phase == Phase.COUNTDOWN:
            if elapsed >= self._countdown_seconds:
                self._start_point()
        elif self._phase == Phase.SETTLE:
            if elapsed >= self._settle_seconds:
                self._start_sampling()
        elif self._phase == Phase.SAMPLE:
            if (
                not self._head_control
                and elapsed >= self._stable_seconds
                and not self._motion_hint
            ):
                self._motion_hint = True
                self.update(
                    QRect(0, int(self.height()) - 60, int(self.width()), 34)
                )
            self._collect(snap)
            if elapsed >= self._sample_seconds:
                self._finish_point()
        elif self._phase == Phase.RETRY:
            if elapsed >= self.RETRY_SECONDS:
                self._current_samples = []
                self._start_point()
        elif self._phase == Phase.FIT:
            self._fit_model()

        if self._face_found != face_before:
            self.update(
                self.FACE_PILL_RECT.toAlignedRect().adjusted(-4, -4, 4, 4)
            )
            if self._phase == Phase.INTRO:
                self.update(
                    QRect(
                        int(self.width() / 2 - 300),
                        int(self.height() * 0.52 - 100),
                        600,
                        200,
                    )
                )
        self._update_live_regions()

    def _update_live_regions(self) -> None:
        """Repaint only the animated bits instead of the whole screen."""
        if self._phase == Phase.COUNTDOWN:
            self.update(
                QRect(
                    int(self.width() / 2 - 100),
                    int(self.height() * 0.53 - 100),
                    200,
                    240,
                )
            )
        elif self._phase in (Phase.SETTLE, Phase.SAMPLE):
            if self._point_index < len(self._points):
                gx, gy = self._points[self._point_index]
                origin = self.screen.geometry().topLeft()
                x = int(gx - origin.x())
                y = int(gy - origin.y())
                self.update(QRect(x - 55, y - 55, 110, 110))
        elif self._phase == Phase.FIT:
            self.update(
                QRect(
                    int(self.width() / 2 - 50),
                    int(self.height() / 2 - 50),
                    100,
                    140,
                )
            )

    def _update_head_warning(self, features: np.ndarray | None) -> None:
        if self._head_control or self._head_baseline is None or features is None:
            self._head_warning = False
            return
        drift = np.abs(
            np.asarray(features[8:14], dtype=np.float64) - self._head_baseline
        )
        thresholds = np.asarray(
            [0.03, 0.04, 0.03, 0.06, 0.06, 0.01], dtype=np.float64
        )
        self._head_warning = bool(np.any(drift > thresholds))

    def _collect(self, snap) -> None:
        if snap.seq == self._last_seq:
            return
        self._last_seq = snap.seq
        if not snap.face_found or snap.features is None:
            return
        if not self._head_control and snap.openness < 0.045:
            return
        features = np.asarray(snap.features, dtype=np.float64)
        if features.shape != (len(FEATURE_NAMES),):
            return
        if not np.all(np.isfinite(features)):
            return
        elapsed = time.monotonic() - self._phase_started
        entry = (features, float(snap.openness), snap.head_pose)
        if self._head_control or elapsed < self._stable_seconds:
            self._current_samples.append(entry)
        else:
            self._current_motion_samples.append(entry)
        self._all_openness.append(float(snap.openness))

    # -------------------------------------------------------------------- paint
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        width = float(self.width())
        height = float(self.height())

        background = QLinearGradient(0, 0, width, height)
        background.setColorAt(0.0, QColor("#07101d"))
        background.setColorAt(0.55, QColor("#040912"))
        background.setColorAt(1.0, QColor("#02060c"))
        painter.fillRect(self.rect(), background)

        glow = QRadialGradient(
            QPointF(width * 0.5, height * 0.46), max(width, height) * 0.55
        )
        glow.setColorAt(0.0, QColor(34, 211, 238, 18))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(self.rect(), glow)

        self._paint_header(painter, width, height)
        self._paint_preview(painter)
        self._paint_points(painter)

        if self._phase == Phase.INTRO:
            self._paint_intro(painter, width, height)
        elif self._phase == Phase.COUNTDOWN:
            self._paint_countdown(painter, width, height)
        elif self._phase in (Phase.RETRY,):
            self._paint_center_message(
                painter, width, height, self._retry_reason or "Trying again…", AMBER
            )
        elif self._phase == Phase.FIT:
            self._paint_busy(painter, width, height)
        elif self._phase == Phase.RESULT:
            self._paint_result(painter, width, height)
        elif self._phase == Phase.ERROR:
            self._paint_error(painter, width, height)
        painter.end()

    def _paint_header(self, painter: QPainter, width: float, height: float) -> None:
        painter.setPen(TEXT)
        title_font = QFont("Segoe UI", 20)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.drawText(
            QRectF(0, 30, width, 36),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            (
                "eyeLens head calibration"
                if self._head_control
                else "eyeLens eye calibration"
            ),
        )
        painter.setFont(QFont("Segoe UI", 10))
        subtitle_color = MUTED
        if self._head_warning and self._phase in (
            Phase.SETTLE,
            Phase.SAMPLE,
        ):
            subtitle = "Head moved — return to your starting head position."
            subtitle_color = AMBER
        elif self._phase == Phase.RESULT:
            subtitle = "Calibration complete — this is the accuracy it measured."
        elif self._phase == Phase.FIT:
            model_name = "head" if self._head_control else "gaze"
            subtitle = (
                "Finishing your calibration…"
                if self._fit_stage == "final"
                else f"Building your personal {model_name} model…"
            )
        elif self._validating:
            subtitle = (
                "Accuracy check — aim your head at each dot and hold still."
                if self._head_control
                else "Accuracy check — look at each dot with your eyes only."
            )
        elif self._head_control:
            subtitle = (
                "Turn or move your head to face the highlighted dot, then "
                "hold still."
            )
        else:
            subtitle = (
                "Hold still, then slowly move your head left and right while "
                "keeping your eyes on the dot."
            )
        painter.setPen(subtitle_color)
        painter.drawText(
            QRectF(0, 66, width, 24),
            Qt.AlignmentFlag.AlignHCenter,
            subtitle,
        )

        # Progress counter + bar.
        if self._phase not in (Phase.INTRO, Phase.COUNTDOWN):
            total = len(self._points)
            current = min(self._point_index + 1, total)
            painter.setPen(TEXT)
            counter_font = QFont("Segoe UI", 11)
            counter_font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(counter_font)
            text = f"{current} / {total}"
            if self._validating and self._phase not in (Phase.RESULT, Phase.ERROR):
                text = f"check {current} / {total}"
            if self._phase in (Phase.RESULT, Phase.ERROR):
                text = f"{total} / {total}"
            painter.drawText(
                QRectF(width - 190, 34, 160, 24),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                text,
            )
            bar = QRectF(width - 190, 64, 160, 4)
            painter.setBrush(QColor(255, 255, 255, 22))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(bar, 2, 2)
            fraction = current / total if total else 0.0
            if self._phase in (Phase.RESULT,):
                fraction = 1.0
            fill = QRectF(bar.left(), bar.top(), bar.width() * fraction, bar.height())
            painter.setBrush(GREEN if self._validating else BRAND)
            painter.drawRoundedRect(fill, 2, 2)

        # Face status pill, under the eye preview.
        pill = QRectF(self.FACE_PILL_RECT)
        color = GREEN if self._face_found else RED
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color.red(), color.green(), color.blue(), 24))
        painter.drawRoundedRect(pill, 14, 14)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(pill.left() + 15, pill.center().y()), 4, 4)
        painter.setPen(color)
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(
            pill.adjusted(28, 0, -8, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "Face detected" if self._face_found else "Face not found",
        )

        if self._phase == Phase.SETTLE or self._phase == Phase.SAMPLE:
            if self._head_control:
                if self._phase == Phase.SAMPLE:
                    hint = "Hold your head still — sampling this position…"
                else:
                    hint = "Aim your head at the highlighted dot…"
            elif self._phase == Phase.SAMPLE:
                sample_elapsed = time.monotonic() - self._phase_started
                if sample_elapsed < self._stable_seconds:
                    hint = "Hold your gaze — sampling stable position…"
                else:
                    hint = (
                        "Keep your eyes on the dot — slowly move your head "
                        "left and right…"
                    )
            else:
                hint = "Look at the highlighted dot…"
            if self._validating:
                hint = "Accuracy check · " + hint
            if self._head_warning:
                hint = "Head moved — return to your starting head position"
                painter.setPen(AMBER)
            else:
                painter.setPen(MUTED)
            painter.setFont(QFont("Segoe UI", 10))
            painter.drawText(
                QRectF(0, height - 52, width, 22),
                Qt.AlignmentFlag.AlignHCenter,
                hint + "   ·   Esc to cancel",
            )
        elif self._phase in (Phase.INTRO, Phase.COUNTDOWN):
            painter.setPen(QColor(120, 140, 160))
            painter.setFont(QFont("Segoe UI", 9))
            painter.drawText(
                QRectF(0, height - 52, width, 22),
                Qt.AlignmentFlag.AlignHCenter,
                "Esc to cancel",
            )

    def _paint_preview(self, painter: QPainter) -> None:
        rect = QRectF(self.PREVIEW_RECT)
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(rect, QColor(4, 10, 18))
        main = (
            self._preview
            if self._head_control
            else (
                self._eye_preview
                if self._face_found
                and self._eye_preview is not None
                and not self._eye_preview.isNull()
                else self._preview
            )
        )
        if main is not None and not main.isNull():
            painter.drawImage(rect, main)
        else:
            painter.setPen(MUTED)
            painter.setFont(QFont("Segoe UI", 9))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "camera preview")

        # Small whole-face inset so the user can still check framing.  Head
        # control already shows the whole face, so it is not needed there.
        if (
            not self._head_control
            and self._preview is not None
            and not self._preview.isNull()
        ):
            inset = QRectF(rect.right() - 96, rect.bottom() - 58, 88, 50)
            painter.fillRect(inset, QColor(4, 10, 18))
            painter.drawImage(inset, self._preview)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(125, 211, 252, 90), 1))
            painter.drawRect(inset)
            painter.setPen(QColor(180, 210, 235, 180))
            painter.setFont(QFont("Segoe UI", 6))
            painter.drawText(
                inset.adjusted(4, 0, -4, -2),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                "FACE",
            )
        painter.restore()

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 26), 1))
        painter.drawRoundedRect(rect, 14, 14)

        painter.setPen(QColor(180, 200, 220, 130))
        painter.setFont(QFont("Segoe UI", 7))
        has_eyes = (
            self._face_found
            and self._eye_preview is not None
            and not self._eye_preview.isNull()
        )
        preview_label = (
            "FACE" if self._head_control else "EYES" if has_eyes else "CAMERA"
        )
        painter.drawText(
            rect.adjusted(10, 6, -100, -6),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            preview_label,
        )

    def _paint_points(self, painter: QPainter) -> None:
        if self._phase in (Phase.INTRO, Phase.COUNTDOWN, Phase.RESULT, Phase.ERROR):
            alpha = 0.35
        else:
            alpha = 1.0
        active = GREEN if self._validating else BRAND
        active_rgb = (
            (52, 211, 153) if self._validating else (56, 189, 248)
        )
        origin = self.screen.geometry().topLeft()
        for index, (gx, gy) in enumerate(self._points):
            point = QPointF(gx - origin.x(), gy - origin.y())
            if index < self._point_index or self._phase in (
                Phase.RESULT,
                Phase.ERROR,
            ):
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(
                    QColor(active_rgb[0], active_rgb[1], active_rgb[2], int(45 * alpha))
                )
                painter.drawEllipse(point, 4, 4)
            elif index == self._point_index and self._phase in (
                Phase.SETTLE,
                Phase.SAMPLE,
            ):
                elapsed = time.monotonic() - self._phase_started
                pulse = 0.5 + 0.5 * math.sin(elapsed * 6.5)
                halo = QRadialGradient(point, 46)
                halo.setColorAt(
                    0.0,
                    QColor(
                        active_rgb[0],
                        active_rgb[1],
                        active_rgb[2],
                        int(60 + 55 * pulse),
                    ),
                )
                halo.setColorAt(
                    1.0, QColor(active_rgb[0], active_rgb[1], active_rgb[2], 0)
                )
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(halo)
                painter.drawEllipse(point, 46, 46)

                duration = (
                    self._settle_seconds
                    if self._phase == Phase.SETTLE
                    else self._sample_seconds
                )
                progress = min(1.0, elapsed / max(0.001, duration))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(
                    QPen(
                        QColor(active_rgb[0], active_rgb[1], active_rgb[2], 80),
                        2.5,
                    )
                )
                painter.drawEllipse(point, 26, 26)
                painter.setPen(
                    QPen(
                        active,
                        3.0,
                        Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap,
                    )
                )
                painter.drawArc(
                    QRectF(point.x() - 26, point.y() - 26, 52, 52),
                    90 * 16,
                    -int(360 * 16 * progress),
                )
                painter.setBrush(QColor(235, 249, 255))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(point, 5.5, 5.5)
            else:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(
                    QPen(
                        QColor(
                            active_rgb[0],
                            active_rgb[1],
                            active_rgb[2],
                            int(70 * alpha),
                        ),
                        1,
                    )
                )
                painter.drawEllipse(point, 4, 4)

    def _paint_intro(self, painter: QPainter, width: float, height: float) -> None:
        card = QRectF(width / 2 - 280, height * 0.52 - 92, 560, 184)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(8, 18, 32, 210))
        painter.drawRoundedRect(card, 20, 20)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(125, 211, 252, 45), 1))
        painter.drawRoundedRect(card, 20, 20)

        painter.setPen(TEXT)
        title = QFont("Segoe UI", 16)
        title.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title)
        painter.drawText(
            card.adjusted(24, 22, -24, -110),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            "Ready when you are",
        )
        painter.setFont(QFont("Segoe UI", 10))
        painter.setPen(MUTED)
        if self._head_control:
            instructions = (
                "Sit at a comfortable distance from the screen. Your face should "
                "be well lit and fully visible in the camera preview. You will "
                "aim your head at 25 dots, then 9 accuracy-check dots (about 45 "
                "seconds). Turn or move your head until you are facing each dot, "
                "then hold still for a moment. Your eyes are not used for "
                "control. Calibration starts automatically once your face is "
                "detected."
            )
        else:
            instructions = (
                "Sit at a comfortable distance from the screen. Your face should "
                "be well lit and fully visible in the camera preview. You will "
                "look at 25 dots, then 9 accuracy-check dots (about 80 "
                "seconds). For each dot, hold still for a moment, then slowly "
                "move your head a little left and right while keeping your eyes "
                "on it. This teaches head-position compensation. Calibration "
                "starts automatically once your face is detected."
            )
        painter.drawText(
            card.adjusted(34, 62, -34, -60),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
            | Qt.TextFlag.TextWordWrap,
            instructions,
        )
        hint_color = BRAND_SOFT if self._face_found else QColor(148, 163, 184)
        painter.setPen(hint_color)
        hint_font = QFont("Segoe UI", 10)
        hint_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(hint_font)
        hint = (
            "Press Space to begin now"
            if self._face_found
            else "Waiting for your face…"
        )
        painter.drawText(
            card.adjusted(24, 128, -24, -20),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            hint,
        )

    def _paint_countdown(self, painter: QPainter, width: float, height: float) -> None:
        remaining = max(
            0.0,
            self._countdown_seconds - (time.monotonic() - self._phase_started),
        )
        number = max(1, int(math.ceil(remaining)))
        center = QPointF(width / 2, height * 0.53)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(56, 189, 248, 20))
        painter.drawEllipse(center, 90, 90)
        painter.setPen(BRAND)
        font = QFont("Segoe UI", 54)
        font.setWeight(QFont.Weight.Light)
        painter.setFont(font)
        painter.drawText(
            QRectF(center.x() - 90, center.y() - 70, 180, 140),
            Qt.AlignmentFlag.AlignCenter,
            str(number),
        )
        painter.setPen(MUTED)
        painter.setFont(QFont("Segoe UI", 11))
        painter.drawText(
            QRectF(center.x() - 240, center.y() + 100, 480, 30),
            Qt.AlignmentFlag.AlignCenter,
            self._countdown_note,
        )

    def _paint_center_message(
        self,
        painter: QPainter,
        width: float,
        height: float,
        message: str,
        color: QColor,
    ) -> None:
        card = QRectF(width / 2 - 260, height / 2 - 52, 520, 104)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(8, 18, 32, 220))
        painter.drawRoundedRect(card, 18, 18)
        painter.setPen(color)
        font = QFont("Segoe UI", 12)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(
            card.adjusted(24, 20, -24, -20),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            message,
        )

    def _paint_busy(self, painter: QPainter, width: float, height: float) -> None:
        center = QPointF(width / 2, height / 2)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(56, 189, 248, 80), 3))
        painter.drawEllipse(center, 34, 34)
        painter.setPen(QPen(BRAND, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        start = int((time.monotonic() * 260) % 360 * 16)
        painter.drawArc(
            QRectF(center.x() - 34, center.y() - 34, 68, 68), start, 90 * 16
        )
        painter.setPen(TEXT)
        font = QFont("Segoe UI", 13)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(
            QRectF(center.x() - 260, center.y() + 60, 520, 30),
            Qt.AlignmentFlag.AlignCenter,
            (
                "Checking accuracy on independent points…"
                if self._fit_stage == "final"
                else f"Building your personal "
                f"{'head' if self._head_control else 'gaze'} model…"
            ),
        )

    def _paint_result(self, painter: QPainter, width: float, height: float) -> None:
        model = self._model
        if model is None:
            return
        card = QRectF(width / 2 - 290, height / 2 - 175, 580, 350)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(7, 16, 29, 236))
        painter.drawRoundedRect(card, 24, 24)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(125, 211, 252, 55), 1))
        painter.drawRoundedRect(card, 24, 24)

        good = model.quality_ok
        accent = GREEN if good else AMBER
        painter.setPen(accent)
        title_font = QFont("Segoe UI", 18)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.drawText(
            card.adjusted(24, 30, -24, -250),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            "Calibration complete",
        )

        painter.setPen(TEXT)
        big = QFont("Segoe UI", 34)
        big.setWeight(QFont.Weight.Light)
        painter.setFont(big)
        painter.drawText(
            QRectF(card.left(), card.top() + 86, card.width(), 60),
            Qt.AlignmentFlag.AlignHCenter,
            f"± {model.error_rmse:.0f} px",
        )
        painter.setPen(accent)
        quality_font = QFont("Segoe UI", 12)
        quality_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(quality_font)
        painter.drawText(
            QRectF(card.left(), card.top() + 148, card.width(), 28),
            Qt.AlignmentFlag.AlignHCenter,
            model.quality_label,
        )
        painter.setPen(MUTED)
        painter.setFont(QFont("Segoe UI", 9))
        checked = model.metrics.validation_points > 0
        if checked and model.metrics.pose_weight > 0:
            where = (
                f"Checked on {model.metrics.validation_points} held-out points "
                "(head-pose corrected)"
            )
        elif checked:
            where = (
                f"Checked on {model.metrics.validation_points} independent points"
            )
        else:
            where = "Estimated across the whole screen"
        advice = (
            "Turn your head toward each dot and hold still for a sharper lens."
            if not good and self._head_control
            else (
                "Try again with better lighting and a still head for a sharper lens."
                if not good
                else "You can improve it any time by calibrating again."
            )
        )
        painter.drawText(
            QRectF(card.left() + 40, card.top() + 182, card.width() - 80, 52),
            Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap,
            f"{where} ({model.metrics.n_points} points, "
            f"{model.metrics.n_samples} samples). {advice}",
        )

        painter.setPen(BRAND_SOFT)
        font = QFont("Segoe UI", 10)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(
            QRectF(card.left() + 24, card.bottom() - 62, card.width() - 48, 24),
            Qt.AlignmentFlag.AlignHCenter,
            (
                "Enter  —  use this calibration"
                if good
                else "R  —  try again"
            ),
        )
        painter.setPen(MUTED)
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(
            QRectF(card.left() + 24, card.bottom() - 34, card.width() - 48, 22),
            Qt.AlignmentFlag.AlignHCenter,
            (
                "R — start over    ·    Esc — cancel"
                if good
                else "Esc — cancel"
            ),
        )

    def _paint_error(self, painter: QPainter, width: float, height: float) -> None:
        card = QRectF(width / 2 - 280, height / 2 - 120, 560, 240)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 8, 12, 235))
        painter.drawRoundedRect(card, 22, 22)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(248, 113, 113, 80), 1))
        painter.drawRoundedRect(card, 22, 22)
        painter.setPen(RED)
        title_font = QFont("Segoe UI", 16)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.drawText(
            card.adjusted(24, 26, -24, -160),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            "Calibration needs another try",
        )
        painter.setPen(TEXT)
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(
            card.adjusted(40, 72, -40, -64),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
            | Qt.TextFlag.TextWordWrap,
            self._error_message or "Something went wrong.",
        )
        painter.setPen(BRAND_SOFT)
        font = QFont("Segoe UI", 10)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(
            QRectF(card.left(), card.bottom() - 46, card.width(), 26),
            Qt.AlignmentFlag.AlignHCenter,
            "R — try again    ·    Esc — cancel",
        )

    # ----------------------------------------------------------------- preview
    def set_preview(self, image: QImage) -> None:
        self._preview = image
        self.update(self.PREVIEW_RECT.toAlignedRect())

    def set_eye_preview(self, image: QImage) -> None:
        self._eye_preview = image
        self.update(self.PREVIEW_RECT.toAlignedRect())
