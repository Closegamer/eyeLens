"""Full-screen, guided eye-tracking calibration."""

from __future__ import annotations

import contextlib
import ctypes
import math
import platform
import time
from enum import Enum, auto
from random import Random

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

from ..gaze.features import FEATURE_NAMES
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
    PREVIEW_RECT = QRectF(24, 24, 320, 150)
    FACE_PILL_RECT = QRectF(24, 184, 260, 28)
    VALIDATION_GRID_X = (0.16, 0.5, 0.84)
    VALIDATION_GRID_Y = (0.28, 0.55, 0.82)
    SETTLE_SECONDS = 0.50
    SAMPLE_SECONDS = 1.20
    RETRY_SECONDS = 1.50
    COUNTDOWN_SECONDS = 2.0

    def __init__(
        self,
        tracker: EyeTracker,
        screen,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.tracker = tracker
        self.screen = screen
        self.setWindowTitle("eyeLens calibration")
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
        self._samples: list[np.ndarray] = []
        self._targets: list[list[float]] = []
        self._point_id_list: list[int] = []
        self._pose_list: list[np.ndarray | None] = []
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
        self._error_message = ""
        self._done = False
        self._fit_started = False
        self._fit_stage = "primary"
        self._validating = False
        self._validation_start = 0
        self._countdown_seconds = self.COUNTDOWN_SECONDS
        self._countdown_note = "Get comfortable and keep looking at the screen"
        self._primary_points = self._build_points()
        self._validation_points = self._build_validation_points()
        self._points = self._primary_points

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ---------------------------------------------------------------- geometry
    @staticmethod
    def _spread_order(
        points: list[tuple[float, float]],
    ) -> list[tuple[float, float]]:
        """Centre first, then a fixed shuffle.

        A row-major or centre-out order correlates slow head drift with target
        position.  Shuffling spreads that drift across the screen and gives the
        model much better held-out behaviour.
        """
        if not points:
            return points
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        center_x = (min(xs) + max(xs)) * 0.5
        center_y = (min(ys) + max(ys)) * 0.5
        center_point = min(
            points,
            key=lambda point: (point[0] - center_x) ** 2
            + (point[1] - center_y) ** 2,
        )
        rest = [point for point in points if point != center_point]
        Random(20261109).shuffle(rest)
        return [center_point] + rest

    def _build_points(self) -> list[tuple[float, float]]:
        geometry = self.screen.geometry()
        width = float(geometry.width())
        height = float(geometry.height())
        top_y = max(height * self.GRID_Y_TOP, 230.0)
        bottom_y = height * self.GRID_Y_BOTTOM
        xs = [geometry.left() + width * frac for frac in self.GRID_X]
        ys = [
            geometry.top() + top_y + (bottom_y - top_y) * index / 4.0
            for index in range(5)
        ]
        return self._spread_order([(x, y) for y in ys for x in xs])

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
        return self._spread_order([(x, y) for y in ys for x in xs])

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
        if self._model is None or self._done:
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
        self._samples = []
        self._targets = []
        self._point_id_list = []
        self._pose_list = []
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
        self._countdown_note = "Get comfortable and keep looking at the screen"
        self._points = self._primary_points
        self._begin_countdown()

    def _start_point(self) -> None:
        self._current_samples = []
        self._last_seq = -1
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
        self._last_seq = -1
        self._validation_start = len(self._samples)
        self._fit_started = False
        self._fit_stage = "final"
        self._countdown_seconds = 1.5
        self._countdown_note = "Accuracy check — keep looking at the screen"
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
                        "Hold still — I lost your eyes. Trying this point again…"
                        if accepted is None
                        else "Not enough steady samples. Trying this point again…"
                    )
                self._enter(Phase.RETRY)
            else:
                self._error_message = (
                    "Eye tracking was not stable enough. Improve the lighting, "
                    "keep your head still, and make sure your face is fully visible."
                )
                self._enter(Phase.ERROR)
            return

        target = self._points[self._point_index]
        if not self._validating and self._point_index == 0:
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

    def _available_pose_samples(self) -> np.ndarray | None:
        if (
            not self._pose_list
            or len(self._pose_list) != len(self._samples)
            or any(pose is None for pose in self._pose_list)
        ):
            return None
        return np.vstack(self._pose_list)

    def _select_pose_correction(
        self, primary: GazeModel
    ) -> tuple[float, float, float]:
        """Choose whether a global head-pose correction helps held-out points.

        Returns (validation_rmse, pose_alpha, pose_weight).  The correction is
        fitted on the primary training residuals and accepted only if it
        improves the independent 9-point validation by at least 2%.
        """
        base_validation = self._validation_error(primary)
        poses = self._available_pose_samples()
        start = self._validation_start
        if (
            poses is None
            or start <= 0
            or start >= len(self._samples)
            or self._primary_model is None
        ):
            return base_validation, 0.0, 0.0
        primary_targets = np.asarray(
            self._targets[:start], dtype=np.float64
        )
        validation_targets = np.asarray(
            self._targets[start:], dtype=np.float64
        )
        validation_ids = np.asarray(
            self._point_id_list[start:], dtype=np.int64
        )
        primary_predictions = np.asarray(
            [
                [prediction.x, prediction.y]
                for prediction in (
                    primary.predict(row) for row in self._samples[:start]
                )
            ],
            dtype=np.float64,
        )
        base_validation_predictions = np.asarray(
            [
                [prediction.x, prediction.y]
                for prediction in (
                    primary.predict(row) for row in self._samples[start:]
                )
            ],
            dtype=np.float64,
        )
        residuals = primary_targets - primary_predictions
        best_validation = base_validation
        best_alpha = 0.0
        best_weight = 0.0
        for alpha in POSE_ALPHAS:
            correction = fit_pose_correction(
                poses[:start], residuals, float(alpha)
            )
            corrected = base_validation_predictions + np.asarray(
                [correction.apply(pose) for pose in poses[start:]],
                dtype=np.float64,
            )
            value = self._point_rmse(
                corrected, validation_targets, validation_ids
            )
            if (
                value < best_validation * 0.97
                and best_validation - value >= 5.0
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
                )
                self._start_validation(self._primary_model)
                return

            validation_rmse = 0.0
            pose_alpha = 0.0
            pose_weight = 0.0
            if self._primary_model is not None:
                (
                    validation_rmse,
                    pose_alpha,
                    pose_weight,
                ) = self._select_pose_correction(self._primary_model)
            final_poses = (
                self._available_pose_samples() if pose_weight > 0 else None
            )
            self._model = GazeModel.fit(
                samples=samples,
                targets=targets,
                point_ids=point_ids,
                openness_threshold=threshold,
                screen=info,
                validation_rmse=validation_rmse,
                validation_points=len(self._validation_points),
                pose_samples=final_poses,
                pose_alpha=pose_alpha,
                pose_weight=pose_weight,
            )
            # Keep all dots visible and completed on the result screen.
            self._points = self._primary_points + self._validation_points
            self._point_index = len(self._points)
            self._enter(Phase.RESULT)
        except (ValueError, IndexError) as exc:
            self._error_message = f"Could not build the calibration model: {exc}"
            self._enter(Phase.ERROR)

    def _filter_current_samples(
        self,
    ) -> tuple[np.ndarray, np.ndarray | None] | None:
        if len(self._current_samples) < 7:
            return None
        openness = np.array([item[1] for item in self._current_samples])
        median_open = float(np.median(openness))
        threshold = max(0.055, median_open * 0.55)
        entries = [
            (features, pose)
            for features, value, pose in self._current_samples
            if value >= threshold
        ]
        if len(entries) < 6:
            return None
        matrix = np.vstack([entry[0] for entry in entries])
        poses = [entry[1] for entry in entries]

        def apply_keep(keep: np.ndarray) -> None:
            nonlocal matrix, poses
            matrix = matrix[keep]
            poses = [pose for pose, keep_row in zip(poses, keep) if keep_row]

        median = np.median(matrix, axis=0)
        mad = np.median(np.abs(matrix - median), axis=0) * 1.4826
        valid_dims = mad > 1e-6
        if np.any(valid_dims):
            deviation = np.abs(matrix[:, valid_dims] - median[valid_dims])
            z = deviation / mad[valid_dims]
            apply_keep(np.max(z, axis=1) <= 4.25)
            if matrix.shape[0] > 2:
                # One refinement pass with the cleaned data.
                median = np.median(matrix, axis=0)
                mad = np.median(np.abs(matrix - median), axis=0) * 1.4826
                valid_dims = mad > 1e-6
                if np.any(valid_dims):
                    deviation = np.abs(
                        matrix[:, valid_dims] - median[valid_dims]
                    )
                    z = deviation / mad[valid_dims]
                    apply_keep(np.max(z, axis=1) <= 4.0)
        if matrix.shape[0] < 6:
            return None
        pose_matrix = (
            None
            if any(pose is None for pose in poses)
            else np.vstack(poses)
        )
        return matrix, pose_matrix

    # -------------------------------------------------------------------- timer
    def _tick(self) -> None:
        now = time.monotonic()
        snap = self.tracker.snapshot()
        face_before = self._face_found
        self._face_found = snap.face_found
        warning_before = self._head_warning
        self._update_head_warning(
            snap.features if snap.face_found else None
        )
        if warning_before != self._head_warning:
            self.update(QRect(0, 60, int(self.width()), 34))
            self.update(QRect(0, int(self.height()) - 60, int(self.width()), 34))
        if snap.face_found:
            if self._face_since is None:
                self._face_since = now
        else:
            self._face_since = None

        elapsed = now - self._phase_started
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
            if elapsed >= self.SETTLE_SECONDS:
                self._start_sampling()
        elif self._phase == Phase.SAMPLE:
            self._collect(snap)
            if elapsed >= self.SAMPLE_SECONDS:
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
                self.update(QRect(x - 38, y - 38, 76, 76))
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
        if self._head_baseline is None or features is None:
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
        if snap.openness < 0.045:
            return
        if self._head_warning:
            return
        features = np.asarray(snap.features, dtype=np.float64)
        if features.shape != (len(FEATURE_NAMES),):
            return
        if not np.all(np.isfinite(features)):
            return
        self._current_samples.append(
            (features, float(snap.openness), snap.head_pose)
        )
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
            "eyeLens calibration",
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
            subtitle = (
                "Finishing your calibration…"
                if self._fit_stage == "final"
                else "Building your personal gaze model…"
            )
        elif self._validating:
            subtitle = "Accuracy check — look at each dot with your eyes only."
        else:
            subtitle = "Look at each dot with your eyes only. Keep your head still."
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
            hint = (
                "Hold your gaze — sampling…"
                if self._phase == Phase.SAMPLE
                else "Look at the highlighted dot…"
            )
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
            self._eye_preview
            if self._face_found
            and self._eye_preview is not None
            and not self._eye_preview.isNull()
            else self._preview
        )
        if main is not None and not main.isNull():
            painter.drawImage(rect, main)
        else:
            painter.setPen(MUTED)
            painter.setFont(QFont("Segoe UI", 9))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "camera preview")

        # Small whole-face inset so the user can still check framing.
        if self._preview is not None and not self._preview.isNull():
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
        painter.drawText(
            rect.adjusted(10, 6, -100, -6),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            "EYES" if has_eyes else "CAMERA",
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
                halo = QRadialGradient(point, 32)
                halo.setColorAt(
                    0.0,
                    QColor(
                        active_rgb[0],
                        active_rgb[1],
                        active_rgb[2],
                        int(45 + 35 * pulse),
                    ),
                )
                halo.setColorAt(
                    1.0, QColor(active_rgb[0], active_rgb[1], active_rgb[2], 0)
                )
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(halo)
                painter.drawEllipse(point, 32, 32)

                duration = (
                    self.SETTLE_SECONDS
                    if self._phase == Phase.SETTLE
                    else self.SAMPLE_SECONDS
                )
                progress = min(1.0, elapsed / max(0.001, duration))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(
                    QPen(
                        QColor(active_rgb[0], active_rgb[1], active_rgb[2], 60),
                        2,
                    )
                )
                painter.drawEllipse(point, 20, 20)
                painter.setPen(
                    QPen(
                        active,
                        2.5,
                        Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap,
                    )
                )
                painter.drawArc(
                    QRectF(point.x() - 20, point.y() - 20, 40, 40),
                    90 * 16,
                    -int(360 * 16 * progress),
                )
                painter.setBrush(QColor(235, 249, 255))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(point, 4.5, 4.5)
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
        painter.drawText(
            card.adjusted(34, 62, -34, -60),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
            | Qt.TextFlag.TextWordWrap,
            "Sit at a comfortable distance from the screen. Your face should be "
            "well lit and fully visible in the camera preview. You will look at "
            "25 dots, then 9 accuracy-check dots (about 50 seconds). The "
            "calibration starts automatically once your face is detected.",
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
                else "Building your personal gaze model…"
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
        painter.drawText(
            QRectF(card.left() + 40, card.top() + 182, card.width() - 80, 52),
            Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap,
            f"{where} ({model.metrics.n_points} points, "
            f"{model.metrics.n_samples} samples). "
            + (
                "You can improve it any time by calibrating again."
                if good
                else "Try again with better lighting and a still head for a sharper lens."
            ),
        )

        painter.setPen(BRAND_SOFT)
        font = QFont("Segoe UI", 10)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(
            QRectF(card.left() + 24, card.bottom() - 62, card.width() - 48, 24),
            Qt.AlignmentFlag.AlignHCenter,
            "Enter  —  use this calibration",
        )
        painter.setPen(MUTED)
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(
            QRectF(card.left() + 24, card.bottom() - 34, card.width() - 48, 22),
            Qt.AlignmentFlag.AlignHCenter,
            "R — start over    ·    Esc — cancel",
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
