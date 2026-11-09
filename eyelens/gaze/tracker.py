"""Webcam capture + MediaPipe face landmark tracking thread."""

from __future__ import annotations

import contextlib
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from .features import EyeFeatures, extract_features, extract_head_pose

PREVIEW_WIDTH = 480
PREVIEW_HEIGHT = 270
EYE_PREVIEW_WIDTH = 640
EYE_PREVIEW_HEIGHT = 300
EYE_LANDMARKS = (
    33,
    133,
    159,
    145,
    468,
    362,
    263,
    386,
    374,
    473,
    70,
    63,
    105,
    66,
    107,
    300,
    293,
    334,
    296,
    336,
)


def eye_crop_box(
    eye_points: np.ndarray, frame_width: int, frame_height: int
) -> tuple[int, int, int, int] | None:
    """Return a zoomed, fixed-aspect crop around both eyes.

    ``eye_points`` are pixel coordinates in the (already mirrored) frame.
    The crop is centred on the eye/eyebrow band and clamped to the frame.
    """
    if eye_points.size == 0:
        return None
    min_x = float(np.min(eye_points[:, 0]))
    max_x = float(np.max(eye_points[:, 0]))
    min_y = float(np.min(eye_points[:, 1]))
    max_y = float(np.max(eye_points[:, 1]))
    span_x = max(max_x - min_x, 4.0)
    span_y = max(max_y - min_y, 4.0)
    aspect = EYE_PREVIEW_WIDTH / EYE_PREVIEW_HEIGHT
    crop_w = max(span_x * 2.2, 160.0)
    crop_h = max(crop_w / aspect, span_y * 1.8)
    crop_w = max(crop_w, crop_h * aspect)
    crop_w = min(crop_w, float(frame_width))
    crop_h = min(crop_h, float(frame_height))
    if crop_w < 1.0 or crop_h < 1.0:
        return None
    center_x = (min_x + max_x) * 0.5
    center_y = (min_y + max_y) * 0.5
    x0 = int(round(min(max(center_x - crop_w / 2.0, 0.0), frame_width - crop_w)))
    y0 = int(round(min(max(center_y - crop_h / 2.0, 0.0), frame_height - crop_h)))
    x1 = min(frame_width, x0 + int(round(crop_w)))
    y1 = min(frame_height, y0 + int(round(crop_h)))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    return x0, y0, x1, y1


@dataclass(frozen=True)
class TrackerSnapshot:
    seq: int
    features: np.ndarray | None
    openness: float
    face_found: bool
    timestamp: float
    fps: float
    head_pose: np.ndarray | None = None

    @property
    def eyes_open(self) -> bool:
        return self.face_found and self.openness >= 0.08


class EyeTracker(QThread):
    """Runs camera + MediaPipe inference without blocking the UI thread."""

    preview_ready = Signal(QImage)
    eyes_preview_ready = Signal(QImage)
    status_changed = Signal(str)
    face_changed = Signal(bool)
    fps_changed = Signal(float)
    error = Signal(str)
    ready = Signal(bool)

    def __init__(
        self,
        model_path: Path | None,
        camera_index: int = 0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.model_path = Path(model_path) if model_path else None
        self.camera_index = int(camera_index)
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._snapshot = TrackerSnapshot(0, None, 0.0, False, 0.0, 0.0)
        self._history: deque[TrackerSnapshot] = deque(maxlen=120)
        self._preview_requests = 0
        self._status = "Camera stopped"
        self._error = ""
        self._seq = 0
        self._ready = False

    # ------------------------------------------------------------- lifecycle
    def stop(self) -> None:
        self._stop_event.set()

    def stop_and_wait(self, timeout_ms: int = 5000) -> None:
        self.stop()
        if self.isRunning():
            self.wait(timeout_ms)

    # --------------------------------------------------------------- preview
    def acquire_preview(self) -> None:
        with self._lock:
            self._preview_requests += 1

    def release_preview(self) -> None:
        with self._lock:
            self._preview_requests = max(0, self._preview_requests - 1)

    # ------------------------------------------------------------------ state
    @property
    def status_text(self) -> str:
        with self._lock:
            return self._status

    @property
    def error_text(self) -> str:
        with self._lock:
            return self._error

    @property
    def is_ready(self) -> bool:
        with self._lock:
            return self._ready

    def snapshot(self) -> TrackerSnapshot:
        with self._lock:
            return self._snapshot

    def recent_features(
        self, seconds: float = 0.5, since: float | None = None
    ) -> np.ndarray | None:
        """Robust median eye features from the last part of a fixation.

        Used by the mouse-drag correction: after the user releases the lens we
        wait a short moment, then take the recent frames where the face was
        visible and the eyes were open.  Per-feature MAD rejection removes
        blinks and single-frame landmark glitches.
        """
        cutoff = time.monotonic() - max(0.05, float(seconds))
        if since is not None:
            cutoff = max(cutoff, float(since))
        with self._lock:
            history = list(self._history)
        rows = [
            snap.features
            for snap in history
            if snap.timestamp >= cutoff
            and snap.face_found
            and snap.features is not None
            and snap.openness >= 0.05
        ]
        if len(rows) < 3:
            return None
        matrix = np.vstack(rows)
        median = np.median(matrix, axis=0)
        mad = np.median(np.abs(matrix - median), axis=0) * 1.4826
        valid = mad > 1e-6
        if np.any(valid):
            deviation = np.abs(matrix[:, valid] - median[valid])
            keep = np.max(deviation / mad[valid], axis=1) <= 3.5
            if int(np.count_nonzero(keep)) >= 3:
                matrix = matrix[keep]
        return np.median(matrix, axis=0)

    def recent_head_pose(
        self, seconds: float = 0.5, since: float | None = None
    ) -> np.ndarray | None:
        """Median head pose from the recent hold window, if available."""
        cutoff = time.monotonic() - max(0.05, float(seconds))
        if since is not None:
            cutoff = max(cutoff, float(since))
        with self._lock:
            history = list(self._history)
        poses = [
            snap.head_pose
            for snap in history
            if snap.timestamp >= cutoff
            and snap.face_found
            and snap.head_pose is not None
        ]
        if len(poses) < 3:
            return None
        return np.median(np.vstack(poses), axis=0)

    def _set_status(self, text: str) -> None:
        with self._lock:
            changed = text != self._status
            self._status = text
        if changed:
            self.status_changed.emit(text)

    def _set_snapshot(self, snapshot: TrackerSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot
            self._history.append(snapshot)

    # -------------------------------------------------------------------- run
    def run(self) -> None:
        cap = None
        landmarker = None
        try:
            import cv2
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision

            try:
                import absl.logging

                absl.logging.set_verbosity(absl.logging.ERROR)
            except Exception:
                pass

            if self.model_path is None or not self.model_path.is_file():
                self._fail(
                    "Face tracking model is missing. Run scripts/download_model.py "
                    "or restart eyeLens with an internet connection."
                )
                return

            self._set_status("Loading face tracking model…")
            options = vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(
                    model_asset_path=str(self.model_path)
                ),
                running_mode=vision.RunningMode.VIDEO,
                num_faces=1,
                min_face_detection_confidence=0.5,
                min_face_presence_confidence=0.5,
                min_tracking_confidence=0.5,
                output_facial_transformation_matrixes=True,
            )
            landmarker = vision.FaceLandmarker.create_from_options(options)

            if self._stop_event.is_set():
                return
            cap, camera_label = self._open_camera(cv2)
            if cap is None:
                self._fail(
                    "Could not open the webcam. Check Windows camera privacy "
                    "settings and whether another app is using it."
                )
                return
            self._set_status(f"Camera running ({camera_label}) — looking for your face…")
            with self._lock:
                self._ready = True
            self.ready.emit(True)

            frame_count = 0
            fps = 0.0
            fps_window_start = time.perf_counter()
            last_timestamp_ms = 0
            last_preview = 0.0
            last_face: bool | None = None
            started_at = time.perf_counter()
            failed_reads = 0
            self.ready.emit(True)

            while not self._stop_event.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    failed_reads += 1
                    if failed_reads >= 15:
                        self._fail("The webcam stopped delivering frames.")
                        break
                    time.sleep(0.02)
                    continue
                failed_reads = 0

                if frame.ndim == 2:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
                else:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                height, width = rgb.shape[:2]
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                timestamp_ms = int((time.perf_counter() - started_at) * 1000)
                if timestamp_ms <= last_timestamp_ms:
                    timestamp_ms = last_timestamp_ms + 1
                last_timestamp_ms = timestamp_ms

                result = landmarker.detect_for_video(mp_image, timestamp_ms)
                frame_count += 1
                now = time.perf_counter()
                if now - fps_window_start >= 1.0:
                    fps = frame_count / (now - fps_window_start)
                    frame_count = 0
                    fps_window_start = now
                    self.fps_changed.emit(fps)

                features: EyeFeatures | None = None
                face_found = bool(result.face_landmarks)
                head_pose = None
                if face_found:
                    features = extract_features(
                        result.face_landmarks[0], width, height
                    )
                    face_found = features is not None
                    if result.facial_transformation_matrixes:
                        head_pose = extract_head_pose(
                            result.facial_transformation_matrixes[0]
                        )

                if face_found != last_face:
                    last_face = face_found
                    self.face_changed.emit(face_found)
                    self._set_status(
                        "Tracking your eyes"
                        if face_found
                        else "Looking for your face…"
                    )

                self._seq += 1
                self._set_snapshot(
                    TrackerSnapshot(
                        seq=self._seq,
                        features=features.values if features else None,
                        openness=features.openness if features else 0.0,
                        face_found=face_found,
                        # recent_features() and the correction hold use the
                        # monotonic clock, not perf_counter.
                        timestamp=time.monotonic(),
                        fps=fps,
                        head_pose=head_pose,
                    )
                )

                with self._lock:
                    wants_preview = self._preview_requests > 0
                if wants_preview and now - last_preview >= 1.0 / 15.0:
                    last_preview = now
                    self._emit_preview(cv2, frame, result.face_landmarks)
        except Exception:  # pragma: no cover - hardware/driver dependent
            traceback.print_exc()
            self._fail("Eye tracking stopped unexpectedly. Check the log for details.")
        finally:
            if cap is not None:
                with contextlib.suppress(Exception):
                    cap.release()
            if landmarker is not None:
                with contextlib.suppress(Exception):
                    landmarker.close()
            with self._lock:
                self._ready = False
            self.ready.emit(False)
            self._set_status("Camera stopped")

    # ----------------------------------------------------------------- helpers
    def _fail(self, message: str) -> None:
        with self._lock:
            self._error = message
            self._status = message
        self.error.emit(message)
        self.status_changed.emit(message)

    def _open_camera(self, cv2):
        import platform

        system = platform.system()
        if system == "Windows":
            candidates = [
                (cv2.CAP_MSMF, 1280, 720, "MSMF 720p"),
                (cv2.CAP_DSHOW, 640, 480, "DirectShow 480p"),
                (cv2.CAP_ANY, 640, 480, "auto 480p"),
            ]
        else:
            candidates = [
                (cv2.CAP_ANY, 1280, 720, "720p"),
                (cv2.CAP_ANY, 640, 480, "480p"),
            ]

        for api, width, height, label in candidates:
            if self._stop_event.is_set():
                return None, label
            cap = cv2.VideoCapture(self.camera_index, api)
            if not cap.isOpened():
                cap.release()
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            cap.set(cv2.CAP_PROP_FPS, 30)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            ok = False
            for _ in range(5):
                ok, frame = cap.read()
                if ok and frame is not None:
                    break
            if ok:
                actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                return cap, f"{label} {actual_w}x{actual_h}"
            cap.release()
        return None, ""

    @staticmethod
    def _to_qimage(cv2, image) -> QImage:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        return QImage(
            rgb.data,
            image.shape[1],
            image.shape[0],
            rgb.strides[0],
            QImage.Format.Format_RGB888,
        ).copy()

    def _emit_preview(self, cv2, frame, landmarks) -> None:
        try:
            preview = frame
            if preview.ndim == 2:
                preview = cv2.cvtColor(preview, cv2.COLOR_GRAY2BGR)
            preview = cv2.flip(preview, 1)
            height, width = preview.shape[:2]
            points = landmarks[0] if landmarks else None
            eye_crop = None
            eye_box = None
            if points is not None:
                # Flip x coordinates so the preview behaves like a mirror.
                def pt(index: int) -> tuple[int, int]:
                    lm = points[index]
                    return int((1.0 - lm.x) * width), int(lm.y * height)

                eye_points = np.asarray(
                    [pt(index) for index in EYE_LANDMARKS], dtype=np.float64
                )
                eye_box = eye_crop_box(eye_points, width, height)
                if eye_box is not None:
                    x0, y0, x1, y1 = eye_box
                    # Copy: the full preview gets markers drawn after this.
                    eye_crop = preview[y0:y1, x0:x1].copy()

                xs = []
                ys = []
                for idx in (10, 152, 234, 454):
                    x, y = pt(idx)
                    xs.append(x)
                    ys.append(y)
                if xs:
                    x0, x1 = max(0, min(xs)), min(width - 1, max(xs))
                    y0, y1 = max(0, min(ys)), min(height - 1, max(ys))
                    cv2.rectangle(preview, (x0, y0), (x1, y1), (90, 90, 90), 1)

                for outer, inner, upper, lower, iris in (
                    (33, 133, 159, 145, 468),
                    (362, 263, 386, 374, 473),
                ):
                    p_outer = pt(outer)
                    p_inner = pt(inner)
                    cv2.line(preview, p_outer, p_inner, (160, 160, 160), 1)
                    for eye_point in (upper, lower):
                        cv2.circle(preview, pt(eye_point), 1, (160, 160, 160), -1)
                    cv2.circle(preview, pt(iris), 3, (40, 210, 255), -1)
                    cv2.circle(preview, pt(iris), 5, (40, 120, 160), 1)
                cv2.circle(preview, pt(1), 2, (200, 200, 200), -1)

            full = cv2.resize(
                preview,
                (PREVIEW_WIDTH, PREVIEW_HEIGHT),
                interpolation=cv2.INTER_AREA,
            )
            self.preview_ready.emit(self._to_qimage(cv2, full))

            if eye_crop is not None and eye_box is not None:
                x0, y0, x1, y1 = eye_box
                eye_preview = cv2.resize(
                    eye_crop,
                    (EYE_PREVIEW_WIDTH, EYE_PREVIEW_HEIGHT),
                    interpolation=cv2.INTER_CUBIC,
                )
                scale_x = EYE_PREVIEW_WIDTH / max(1, x1 - x0)
                scale_y = EYE_PREVIEW_HEIGHT / max(1, y1 - y0)

                def eye_pt(index: int) -> tuple[int, int]:
                    x, y = pt(index)
                    return (
                        int(round((x - x0) * scale_x)),
                        int(round((y - y0) * scale_y)),
                    )

                for outer, inner, upper, lower, iris in (
                    (33, 133, 159, 145, 468),
                    (362, 263, 386, 374, 473),
                ):
                    cv2.line(
                        eye_preview,
                        eye_pt(outer),
                        eye_pt(inner),
                        (160, 160, 160),
                        1,
                    )
                    for eye_point in (upper, lower):
                        cv2.circle(
                            eye_preview,
                            eye_pt(eye_point),
                            2,
                            (160, 160, 160),
                            -1,
                        )
                    cv2.circle(
                        eye_preview, eye_pt(iris), 5, (40, 210, 255), -1
                    )
                    cv2.circle(eye_preview, eye_pt(iris), 8, (40, 120, 160), 1)
                self.eyes_preview_ready.emit(
                    self._to_qimage(cv2, eye_preview)
                )
        except Exception:
            # Preview failures must never stop tracking.
            traceback.print_exc()
