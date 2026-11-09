"""Per-user calibration: polynomial ridge + kernel-ridge residual model.

A single low-order polynomial cannot represent the way a real eye maps to a
screen: gaze is nonlinear near the edges, and head pose/distance modulate the
mapping.  The model here combines:

* a curated quadratic ridge model, which captures the global trend and
  extrapolates sensibly;
* an RBF kernel-ridge model fitted on the ridge residuals, which captures the
  local nonlinearity that the polynomial misses.  Far away from the calibration
  samples the kernel decays to zero, so the stable polynomial prediction is
  used.

Both stages are selected with grouped leave-one-point-out cross-validation:
whole calibration targets are held out, not individual frames, so correlated
frames from the same fixation cannot leak into the score.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .features import FEATURE_NAMES, FEATURE_VERSION, expand_features, expand_matrix

MODEL_VERSION = 2
_MIN_POINTS = 4
_MAX_SAMPLES_PER_POINT = 16
_RIDGE_ALPHAS = np.logspace(-3.0, 4.0, 15)
_KRR_GAMMAS = np.geomspace(0.002, 0.2, 7)
_KRR_ALPHAS = np.logspace(-4.0, 1.0, 6)
# Only use the kernel stage when it beats the polynomial by a meaningful
# margin on held-out targets.
_KRR_MIN_IMPROVEMENT = 0.99


@dataclass(frozen=True)
class CalibrationMetrics:
    train_rmse: float
    loo_rmse: float
    n_points: int
    n_samples: int
    alpha: float
    worst_point_rmse: float
    validation_rmse: float = 0.0
    validation_points: int = 0
    krr_gamma: float = 0.0
    krr_alpha: float = 0.0
    krr_weight: float = 0.0

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
            validation_rmse=float(raw.get("validation_rmse", 0.0)),
            validation_points=int(raw.get("validation_points", 0)),
            krr_gamma=float(raw.get("krr_gamma", 0.0)),
            krr_alpha=float(raw.get("krr_alpha", 0.0)),
            krr_weight=float(raw.get("krr_weight", 0.0)),
        )


@dataclass(frozen=True)
class GazePrediction:
    x: float
    y: float


def _solve(matrix: np.ndarray, rhs: np.ndarray) -> np.ndarray:
    try:
        return np.linalg.solve(matrix, rhs)
    except np.linalg.LinAlgError:
        return np.linalg.lstsq(matrix, rhs, rcond=None)[0]


def _ridge_solve(
    x_centered: np.ndarray, y_centered: np.ndarray, alpha: float
) -> np.ndarray:
    dim = x_centered.shape[1]
    gram = x_centered.T @ x_centered
    gram.flat[:: dim + 1] += alpha
    return _solve(gram, x_centered.T @ y_centered)


def _fit_ridge(
    x: np.ndarray, y: np.ndarray, alpha: float
) -> tuple[np.ndarray, np.ndarray]:
    x_mean = x.mean(axis=0)
    y_mean = y.mean(axis=0)
    coef = _ridge_solve(x - x_mean, y - y_mean, alpha)
    intercept = y_mean - x_mean @ coef
    return coef, intercept


def _rbf_matrix(a: np.ndarray, b: np.ndarray, gamma: float) -> np.ndarray:
    """RBF kernel without materialising an N x M x D tensor."""
    a2 = np.einsum("ij,ij->i", a, a)[:, None]
    b2 = np.einsum("ij,ij->i", b, b)[None, :]
    distance_sq = a2 + b2 - 2.0 * (a @ b.T)
    return np.exp(-gamma * np.maximum(distance_sq, 0.0))


def _fit_krr(
    x: np.ndarray, y: np.ndarray, gamma: float, alpha: float
) -> np.ndarray:
    kernel = _rbf_matrix(x, x, gamma)
    count = kernel.shape[0]
    kernel.flat[:: count + 1] += alpha
    return _solve(kernel, y)


def _per_point_mse(
    targets: np.ndarray, predictions: np.ndarray, point_ids: np.ndarray
) -> dict[int, float]:
    result: dict[int, float] = {}
    for point in np.unique(point_ids):
        mask = point_ids == point
        error = predictions[mask] - targets[mask]
        result[int(point)] = float(np.mean(np.square(error)))
    return result


def _standardize(
    values: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = values.mean(axis=0)
    std = values.std(axis=0)
    std[std < 1e-8] = 1.0
    return mean, std, (values - mean) / std


def _cap_samples(
    samples: np.ndarray,
    targets: np.ndarray,
    point_ids: np.ndarray,
    limit: int = _MAX_SAMPLES_PER_POINT,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Keep the most typical ``limit`` frames per calibration target.

    A 50-second calibration can produce well over a thousand frames.  The
    kernel stage grows cubically with the number of frames, and the extra
    frames are mostly correlated noise.  Keeping the frames closest to each
    target's median preserves normal head jitter while bounding the fit cost.
    """
    selected: list[int] = []
    for point in np.unique(point_ids):
        indices = np.flatnonzero(point_ids == point)
        if indices.size > limit:
            median = np.median(samples[indices], axis=0)
            distance = np.sum(np.square(samples[indices] - median), axis=1)
            indices = indices[np.argsort(distance)[:limit]]
        selected.extend(int(index) for index in indices)
    selected.sort()
    chosen = np.asarray(selected, dtype=np.int64)
    return samples[chosen], targets[chosen], point_ids[chosen]


def _ridge_cv(
    x: np.ndarray, y: np.ndarray, point_ids: np.ndarray, alphas: np.ndarray
) -> tuple[float, float, dict[int, float]]:
    """Grouped LOO for the polynomial ridge stage.

    Returns (best_alpha, best_score, per_point_mse).  The score is the mean
    squared error per held-out target, so every calibration point has equal
    weight regardless of how many frames survived filtering.
    """
    groups = np.unique(point_ids)
    squared: dict[float, dict[int, list[float]]] = {
        float(alpha): {int(g): [] for g in groups} for alpha in alphas
    }

    for point in groups:
        test = point_ids == point
        train = ~test
        x_train = x[train]
        y_train = y[train]
        x_mean = x_train.mean(axis=0)
        y_mean = y_train.mean(axis=0)
        x_centered = x_train - x_mean
        y_centered = y_train - y_mean
        gram = x_centered.T @ x_centered
        rhs = x_centered.T @ y_centered
        for alpha in alphas:
            key = float(alpha)
            regularized = gram.copy()
            regularized.flat[:: regularized.shape[0] + 1] += key
            coef = _solve(regularized, rhs)
            prediction = x[test] @ coef + (y_mean - x_mean @ coef)
            error = prediction - y[test]
            squared[key][int(point)].extend(
                np.square(error).reshape(-1).tolist()
            )

    best_alpha = float(alphas[0])
    best_score = float("inf")
    best_per_point: dict[int, float] = {}
    for alpha in alphas:
        key = float(alpha)
        point_scores = {
            point: float(np.mean(values))
            for point, values in squared[key].items()
            if values
        }
        if not point_scores:
            continue
        score = float(np.mean(list(point_scores.values())))
        if score < best_score:
            best_score = score
            best_alpha = key
            best_per_point = point_scores
    return best_alpha, best_score, best_per_point


def _ridge_fold_data(
    x: np.ndarray, y: np.ndarray, point_ids: np.ndarray, alpha: float
) -> list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    """Per-fold (train_mask, test_mask, train_pred, test_pred) for hybrid CV."""
    folds = []
    for point in np.unique(point_ids):
        test = point_ids == point
        train = ~test
        coef, intercept = _fit_ridge(x[train], y[train], alpha)
        folds.append(
            (
                train,
                test,
                x[train] @ coef + intercept,
                x[test] @ coef + intercept,
            )
        )
    return folds


def _hybrid_cv(
    raw: np.ndarray,
    expanded: np.ndarray,
    targets: np.ndarray,
    point_ids: np.ndarray,
    ridge_alpha: float,
    gammas: np.ndarray,
    alphas: np.ndarray,
) -> tuple[float, float, float, float, dict[int, float]]:
    """Grouped LOO for polynomial + KRR-residual model.

    Returns (gamma, krr_alpha, score, weight, per_point_mse).  ``weight`` is
    1.0 when the hybrid wins; otherwise 0.0.  The polynomial is refitted inside
    every fold so the score is honest.

    Instead of refitting a kernel ridge model for every fold, the exact
    grouped-LOO solution is obtained from the inverse of the full kernel matrix
    with a block-inverse identity.  That turns a many-seconds grid search into
    a sub-second one.
    """
    folds = _ridge_fold_data(expanded, targets, point_ids, ridge_alpha)
    groups = np.unique(point_ids)
    fold_indices = [
        (np.flatnonzero(point_ids != point), np.flatnonzero(point_ids == point))
        for point in groups
    ]
    best = (0.0, 0.0, float("inf"), 0.0, {})

    for gamma in gammas:
        kernel = _rbf_matrix(raw, raw, float(gamma))
        eigenvalues, eigenvectors = np.linalg.eigh(kernel)
        for alpha in alphas:
            inverse_values = 1.0 / (eigenvalues + float(alpha))
            # H^-1 = V diag(1 / (lambda + alpha)) V^T
            inverse = (eigenvectors * inverse_values) @ eigenvectors.T
            predictions = np.zeros_like(targets)
            for (train_index, test_index), fold in zip(
                fold_indices, folds, strict=True
            ):
                _, _, train_pred, test_pred = fold
                residual = targets[train_index] - train_pred
                a = inverse[np.ix_(train_index, train_index)]
                b = inverse[np.ix_(train_index, test_index)]
                c = inverse[np.ix_(test_index, train_index)]
                d = inverse[np.ix_(test_index, test_index)]
                # H_RR^-1 @ residual without materialising H_RR^-1:
                coefficient = a @ residual - b @ _solve(d, c @ residual)
                kernel_test = kernel[np.ix_(test_index, train_index)]
                predictions[test_index] = test_pred + kernel_test @ coefficient
            per_point = _per_point_mse(targets, predictions, point_ids)
            score = float(np.mean(list(per_point.values())))
            if score < best[2]:
                best = (
                    float(gamma),
                    float(alpha),
                    score,
                    1.0,
                    per_point,
                )

    # If the kernel stage is not clearly better, keep the simpler model.
    # The caller compares the score with the ridge-only score.
    return best


class GazeModel:
    """Fitted mapping from :data:`FEATURE_NAMES` to screen coordinates."""

    def __init__(
        self,
        raw_mean: np.ndarray,
        raw_std: np.ndarray,
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
        krr_train: np.ndarray | None = None,
        krr_coef: np.ndarray | None = None,
        krr_gamma: float = 0.0,
        krr_weight: float = 0.0,
        krr_residual_limit: float = 0.0,
        created_at: str | None = None,
    ) -> None:
        self.raw_mean = np.asarray(raw_mean, dtype=np.float64)
        self.raw_std = np.asarray(raw_std, dtype=np.float64)
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
        self.krr_train = (
            np.asarray(krr_train, dtype=np.float64)
            if krr_train is not None
            else np.zeros((0, len(FEATURE_NAMES)))
        )
        self.krr_coef = (
            np.asarray(krr_coef, dtype=np.float64)
            if krr_coef is not None
            else np.zeros((0, 2))
        )
        self.krr_gamma = float(krr_gamma)
        self.krr_weight = float(krr_weight)
        self.krr_residual_limit = float(krr_residual_limit)
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
        validation_rmse: float = 0.0,
        validation_points: int = 0,
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
        samples, targets, point_ids = _cap_samples(
            samples, targets, point_ids
        )
        unique_points = np.unique(point_ids)

        raw_mean, raw_std, raw_scaled = _standardize(samples)
        expanded = expand_matrix(samples)
        mean, std, scaled = _standardize(expanded)

        ridge_alpha, ridge_score, ridge_per_point = _ridge_cv(
            scaled, targets, point_ids, _RIDGE_ALPHAS
        )
        (
            krr_gamma,
            krr_alpha,
            hybrid_score,
            krr_weight,
            hybrid_per_point,
        ) = _hybrid_cv(
            raw_scaled,
            scaled,
            targets,
            point_ids,
            ridge_alpha,
            _KRR_GAMMAS,
            _KRR_ALPHAS,
        )
        if hybrid_score >= ridge_score * _KRR_MIN_IMPROVEMENT:
            krr_weight = 0.0
            selected_per_point = ridge_per_point
            loo_rmse = float(np.sqrt(max(0.0, ridge_score)))
        else:
            selected_per_point = hybrid_per_point
            loo_rmse = float(np.sqrt(max(0.0, hybrid_score)))

        coef, intercept = _fit_ridge(scaled, targets, ridge_alpha)
        train_pred = scaled @ coef + intercept
        train_rmse = float(np.sqrt(np.mean(np.square(train_pred - targets))))

        krr_train: np.ndarray | None = None
        krr_coef: np.ndarray | None = None
        krr_residual_limit = 0.0
        if krr_weight > 0.0:
            train_residual = targets - train_pred
            krr_coef = _fit_krr(
                raw_scaled, train_residual, krr_gamma, krr_alpha
            )
            krr_train = raw_scaled
            residual_norms = np.linalg.norm(train_residual, axis=1)
            # Keep the local correction local.  The 95th percentile covers
            # legitimate regional errors, while the hard bound stops a bad
            # feature frame from throwing the lens across the screen.
            krr_residual_limit = max(
                100.0,
                1.5 * float(np.percentile(residual_norms, 95)),
            )

        worst = float(np.sqrt(max(selected_per_point.values(), default=0.0)))

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
            alpha=float(ridge_alpha),
            worst_point_rmse=worst,
            validation_rmse=float(validation_rmse),
            validation_points=int(validation_points),
            krr_gamma=float(krr_gamma) if krr_weight > 0 else 0.0,
            krr_alpha=float(krr_alpha) if krr_weight > 0 else 0.0,
            krr_weight=float(krr_weight),
        )
        return cls(
            raw_mean=raw_mean,
            raw_std=raw_std,
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
            krr_train=krr_train,
            krr_coef=krr_coef,
            krr_gamma=krr_gamma,
            krr_weight=krr_weight,
            krr_residual_limit=krr_residual_limit,
        )

    # -------------------------------------------------------------- predict
    def predict(self, values: np.ndarray) -> GazePrediction:
        raw = np.asarray(values, dtype=np.float64).reshape(-1)
        if raw.size != len(FEATURE_NAMES):
            raise ValueError(f"expected {len(FEATURE_NAMES)} features")
        raw = np.clip(raw, self.clip_low, self.clip_high)
        raw_scaled = (raw - self.raw_mean) / self.raw_std
        scaled = (expand_features(raw) - self.mean) / self.std
        out = scaled @ self.coef + self.intercept
        if self.krr_weight > 0.0 and self.krr_train.size:
            kernel = _rbf_matrix(
                raw_scaled.reshape(1, -1), self.krr_train, self.krr_gamma
            )[0]
            residual = kernel @ self.krr_coef
            if self.krr_residual_limit > 0.0:
                residual = np.clip(
                    residual,
                    -self.krr_residual_limit,
                    self.krr_residual_limit,
                )
            out = out + self.krr_weight * residual
        return GazePrediction(float(out[0]), float(out[1]))

    def is_eye_open(self, openness: float) -> bool:
        return float(openness) >= self.openness_threshold

    # ---------------------------------------------------------------- quality
    @property
    def error_rmse(self) -> float:
        """Honest error estimate: independent validation when available."""
        if self.metrics.validation_rmse > 0.0:
            return self.metrics.validation_rmse
        return self.metrics.loo_rmse

    @property
    def quality_label(self) -> str:
        rmse = self.error_rmse
        if rmse <= 80.0:
            return "Excellent"
        if rmse <= 150.0:
            return "Good"
        if rmse <= 240.0:
            return "Fair"
        return "Needs recalibration"

    @property
    def quality_ok(self) -> bool:
        return self.error_rmse <= 150.0

    def summary(self) -> str:
        return f"{self.quality_label} · ±{self.error_rmse:.0f} px"

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
            metrics = raw.get("metrics", {})
            validation = (
                float(metrics.get("validation_rmse", 0.0))
                if isinstance(metrics, dict)
                else 0.0
            )
            validation_points = (
                int(metrics.get("validation_points", 0))
                if isinstance(metrics, dict)
                else 0
            )
            model = cls.fit(
                samples=samples,
                targets=targets,
                point_ids=point_ids,
                openness_threshold=float(raw.get("openness_threshold", 0.1)),
                screen=dict(raw.get("screen", {})),
                validation_rmse=validation,
                validation_points=validation_points,
            )
            model.created_at = str(raw.get("created_at", model.created_at))
            return model
        except (KeyError, TypeError, ValueError):
            return None
