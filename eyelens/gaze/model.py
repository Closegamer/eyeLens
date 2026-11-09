"""Per-user calibration: ridge regression from eye features to screen points."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .features import FEATURE_NAMES, FEATURE_VERSION, expand_features, expand_matrix

MODEL_VERSION = 1
_MIN_POINTS = 4
_ALPHAS = np.logspace(-3.0, 4.0, 15)


@dataclass(frozen=True)
class CalibrationMetrics:
    train_rmse: float
    loo_rmse: float
    n_points: int
    n_samples: int
    alpha: float
    worst_point_rmse: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CalibrationMetrics:
        return cls(
            train_rmse=float(raw.get("train_rmse", 0.0)),
            loo_rmse=float(raw.get("loo_rmse", 0.0)),
            n_points=int(raw.get("n_points", 0)),
            n_samples=int(raw.get("n_samples", 0)),
            alpha=float(raw.get("alpha", 1.0)),
            worst_point_rmse=float(raw.get("worst_point_rmse", 0.0)),
        )


@dataclass(frozen=True)
class GazePrediction:
    x: float
    y: float


def _ridge_solve(
    x_centered: np.ndarray, y_centered: np.ndarray, alpha: float
) -> np.ndarray:
    dim = x_centered.shape[1]
    gram = x_centered.T @ x_centered
    gram.flat[:: dim + 1] += alpha
    rhs = x_centered.T @ y_centered
    try:
        return np.linalg.solve(gram, rhs)
    except np.linalg.LinAlgError:
        return np.linalg.lstsq(gram, rhs, rcond=None)[0]


def _fit_ridge(
    x: np.ndarray, y: np.ndarray, alpha: float
) -> tuple[np.ndarray, np.ndarray]:
    x_mean = x.mean(axis=0)
    y_mean = y.mean(axis=0)
    xc = x - x_mean
    yc = y - y_mean
    coef = _ridge_solve(xc, yc, alpha)
    intercept = y_mean - x_mean @ coef
    return coef, intercept


class GazeModel:
    """Fitted mapping from :data:`FEATURE_NAMES` to screen coordinates."""

    def __init__(
        self,
        mean: np.ndarray,
        std: np.ndarray,
        coef: np.ndarray,
        intercept: np.ndarray,
        clip_low: np.ndarray,
        clip_high: np.ndarray,
        openness_threshold: float,
        screen: dict[str, Any],
        metrics: CalibrationMetrics,
        samples: np.ndarray,
        targets: np.ndarray,
        point_ids: np.ndarray,
        created_at: str | None = None,
    ) -> None:
        self.mean = np.asarray(mean, dtype=np.float64)
        self.std = np.asarray(std, dtype=np.float64)
        self.coef = np.asarray(coef, dtype=np.float64)
        self.intercept = np.asarray(intercept, dtype=np.float64)
        self.clip_low = np.asarray(clip_low, dtype=np.float64)
        self.clip_high = np.asarray(clip_high, dtype=np.float64)
        self.openness_threshold = float(openness_threshold)
        self.screen = dict(screen)
        self.metrics = metrics
        self.samples = np.asarray(samples, dtype=np.float64)
        self.targets = np.asarray(targets, dtype=np.float64)
        self.point_ids = np.asarray(point_ids, dtype=np.int64)
        self.created_at = created_at or time.strftime("%Y-%m-%dT%H:%M:%S")

    # ------------------------------------------------------------------ fit
    @classmethod
    def fit(
        cls,
        samples: np.ndarray,
        targets: np.ndarray,
        point_ids: np.ndarray,
        openness_threshold: float,
        screen: dict[str, Any],
    ) -> GazeModel:
        samples = np.asarray(samples, dtype=np.float64)
        targets = np.asarray(targets, dtype=np.float64)
        point_ids = np.asarray(point_ids, dtype=np.int64).reshape(-1)
        if samples.ndim != 2 or samples.shape[1] != len(FEATURE_NAMES):
            raise ValueError("calibration samples have the wrong shape")
        if targets.shape != (samples.shape[0], 2):
            raise ValueError("calibration targets have the wrong shape")
        if point_ids.size != samples.shape[0]:
            raise ValueError("calibration point ids have the wrong shape")
        unique_points = np.unique(point_ids)
        if unique_points.size < _MIN_POINTS:
            raise ValueError(
                f"at least {_MIN_POINTS} calibration points are required"
            )

        expanded = expand_matrix(samples)
        mean = expanded.mean(axis=0)
        std = expanded.std(axis=0)
        std[std < 1e-8] = 1.0
        scaled = (expanded - mean) / std

        best_alpha = float(_ALPHAS[0])
        best_score = float("inf")
        best_per_point: dict[int, float] = {}
        for alpha in _ALPHAS:
            squared: dict[int, list[float]] = {}
            for point in unique_points:
                test_mask = point_ids == point
                train_mask = ~test_mask
                if not np.any(train_mask):
                    continue
                coef, intercept = _fit_ridge(
                    scaled[train_mask], targets[train_mask], float(alpha)
                )
                pred = scaled[test_mask] @ coef + intercept
                err = pred - targets[test_mask]
                squared[int(point)] = np.square(err).reshape(-1).tolist()
            if not squared:
                continue
            per_point = {
                point: float(np.mean(values)) for point, values in squared.items()
            }
            score = float(np.mean(list(per_point.values())))
            if score < best_score:
                best_score = score
                best_alpha = float(alpha)
                best_per_point = per_point

        coef, intercept = _fit_ridge(scaled, targets, best_alpha)
        train_pred = scaled @ coef + intercept
        train_rmse = float(
            np.sqrt(np.mean(np.square(train_pred - targets)))
        )
        loo_rmse = float(np.sqrt(max(0.0, best_score)))
        worst = float(np.sqrt(max(best_per_point.values(), default=0.0)))

        # Clip unseen inputs with a modest extrapolation allowance so a bad
        # blink or an extreme head position cannot send the lens flying.
        raw_range = np.maximum(samples.max(axis=0) - samples.min(axis=0), 1e-6)
        clip_low = samples.min(axis=0) - 0.20 * raw_range
        clip_high = samples.max(axis=0) + 0.20 * raw_range

        metrics = CalibrationMetrics(
            train_rmse=train_rmse,
            loo_rmse=loo_rmse,
            n_points=int(unique_points.size),
            n_samples=int(samples.shape[0]),
            alpha=best_alpha,
            worst_point_rmse=worst,
        )
        return cls(
            mean=mean,
            std=std,
            coef=coef,
            intercept=intercept,
            clip_low=clip_low,
            clip_high=clip_high,
            openness_threshold=float(openness_threshold),
            screen=dict(screen),
            metrics=metrics,
            samples=samples,
            targets=targets,
            point_ids=point_ids,
        )

    # -------------------------------------------------------------- predict
    def predict(self, values: np.ndarray) -> GazePrediction:
        raw = np.asarray(values, dtype=np.float64).reshape(-1)
        if raw.size != len(FEATURE_NAMES):
            raise ValueError(f"expected {len(FEATURE_NAMES)} features")
        raw = np.clip(raw, self.clip_low, self.clip_high)
        scaled = (expand_features(raw) - self.mean) / self.std
        out = scaled @ self.coef + self.intercept
        return GazePrediction(float(out[0]), float(out[1]))

    def is_eye_open(self, openness: float) -> bool:
        return float(openness) >= self.openness_threshold

    # ---------------------------------------------------------------- quality
    @property
    def quality_label(self) -> str:
        rmse = self.metrics.loo_rmse
        if rmse <= 80.0:
            return "Excellent"
        if rmse <= 150.0:
            return "Good"
        if rmse <= 240.0:
            return "Fair"
        return "Needs recalibration"

    @property
    def quality_ok(self) -> bool:
        return self.metrics.loo_rmse <= 150.0

    def summary(self) -> str:
        return f"{self.quality_label} · ±{self.metrics.loo_rmse:.0f} px"

    # ------------------------------------------------------------------- io
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": MODEL_VERSION,
            "feature_version": FEATURE_VERSION,
            "created_at": self.created_at,
            "screen": self.screen,
            "openness_threshold": self.openness_threshold,
            "metrics": self.metrics.to_dict(),
            "samples": self.samples.tolist(),
            "targets": self.targets.tolist(),
            "point_ids": self.point_ids.tolist(),
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(
                json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)

    @classmethod
    def load(cls, path: Path) -> GazeModel | None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict):
            return None
        if int(raw.get("version", 0)) != MODEL_VERSION:
            return None
        if int(raw.get("feature_version", 0)) != FEATURE_VERSION:
            return None
        try:
            samples = np.asarray(raw["samples"], dtype=np.float64)
            targets = np.asarray(raw["targets"], dtype=np.float64)
            point_ids = np.asarray(raw["point_ids"], dtype=np.int64)
            model = cls.fit(
                samples=samples,
                targets=targets,
                point_ids=point_ids,
                openness_threshold=float(raw.get("openness_threshold", 0.1)),
                screen=dict(raw.get("screen", {})),
            )
            model.created_at = str(raw.get("created_at", model.created_at))
            return model
        except (KeyError, TypeError, ValueError):
            return None
