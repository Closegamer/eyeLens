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

from .features import (
    FEATURE_NAMES,
    FEATURE_VERSION,
    HEAD_POSE_FEATURES,
    MODEL_FEATURE_INDICES,
    MODEL_MODE,
    expand_features,
    expand_matrix,
    select_model_features,
)

MODEL_VERSION = 2
_MIN_POINTS = 4
_MAX_SAMPLES_PER_POINT = 16
_RIDGE_ALPHAS = np.logspace(-3.0, 4.0, 15)
_KRR_GAMMAS = np.geomspace(0.002, 0.2, 7)
_KRR_ALPHAS = np.logspace(-4.0, 1.0, 6)
# Only use the kernel stage when it beats the polynomial by a meaningful
# margin on held-out targets.
_KRR_MIN_IMPROVEMENT = 0.99
# Mouse-drag corrections are a local residual memory layered on top of the
# fitted model.  A broad kernel would move unrelated screen regions; a narrow
# one would only help at the exact corrected pixel.
_CORRECTION_GAMMA = 0.06
_CORRECTION_SIMILARITY = 0.60
_CORRECTION_MIN_WEIGHT = 0.02
_MAX_CORRECTIONS = 64


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
    corrections: int = 0
    pose_weight: float = 0.0
    pose_alpha: float = 0.0

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
            corrections=int(raw.get("corrections", 0)),
            pose_weight=float(raw.get("pose_weight", 0.0)),
            pose_alpha=float(raw.get("pose_alpha", 0.0)),
        )


@dataclass(frozen=True)
class GazePrediction:
    x: float
    y: float


@dataclass(frozen=True)
class PoseCorrection:
    """A small global correction from head pose to screen offset."""

    mean: np.ndarray
    std: np.ndarray
    coef: np.ndarray
    intercept: np.ndarray
    clip_low: np.ndarray
    clip_high: np.ndarray
    limit: float

    def apply(self, pose: np.ndarray) -> np.ndarray:
        values = np.asarray(pose, dtype=np.float64).reshape(-1)
        if values.size != self.mean.size or not np.all(np.isfinite(values)):
            return np.zeros(2, dtype=np.float64)
        values = np.clip(values, self.clip_low, self.clip_high)
        scaled = (values - self.mean) / self.std
        offset = scaled @ self.coef + self.intercept
        if self.limit > 0.0:
            offset = np.clip(offset, -self.limit, self.limit)
        return offset


POSE_ALPHAS = np.asarray([0.1, 1.0, 10.0], dtype=np.float64)


def fit_pose_correction(
    poses: np.ndarray, residuals: np.ndarray, alpha: float
) -> PoseCorrection:
    """Ridge-map head pose to a global screen-space residual."""
    poses = np.asarray(poses, dtype=np.float64)
    residuals = np.asarray(residuals, dtype=np.float64)
    if poses.ndim != 2 or residuals.shape != (poses.shape[0], 2):
        raise ValueError("pose correction data has the wrong shape")
    mean = poses.mean(axis=0)
    std = poses.std(axis=0)
    std[std < 1e-8] = 1.0
    scaled = (poses - mean) / std
    x_mean = scaled.mean(axis=0)
    y_mean = residuals.mean(axis=0)
    x_centered = scaled - x_mean
    y_centered = residuals - y_mean
    gram = x_centered.T @ x_centered
    gram.flat[:: gram.shape[0] + 1] += float(alpha)
    coef = _solve(gram, x_centered.T @ y_centered)
    intercept = y_mean - x_mean @ coef
    pose_range = np.maximum(poses.max(axis=0) - poses.min(axis=0), 1e-6)
    clip_low = poses.min(axis=0) - 0.20 * pose_range
    clip_high = poses.max(axis=0) + 0.20 * pose_range
    residual_norms = np.linalg.norm(residuals, axis=1)
    limit = max(120.0, 1.5 * float(np.percentile(residual_norms, 95)))
    return PoseCorrection(
        mean=np.asarray(mean, dtype=np.float64),
        std=np.asarray(std, dtype=np.float64),
        coef=np.asarray(coef, dtype=np.float64),
        intercept=np.asarray(intercept, dtype=np.float64),
        clip_low=np.asarray(clip_low, dtype=np.float64),
        clip_high=np.asarray(clip_high, dtype=np.float64),
        limit=float(limit),
    )


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
    poses: np.ndarray | None = None,
    limit: int = _MAX_SAMPLES_PER_POINT,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray | None]:
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
    chosen_poses = poses[chosen] if poses is not None else None
    return samples[chosen], targets[chosen], point_ids[chosen], chosen_poses


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
        correction_features: np.ndarray | None = None,
        correction_offsets: np.ndarray | None = None,
        pose_correction: PoseCorrection | None = None,
        pose_weight: float = 0.0,
        pose_alpha: float = 0.0,
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
        self.correction_features = (
            np.asarray(correction_features, dtype=np.float64)
            if correction_features is not None
            else np.zeros((0, len(FEATURE_NAMES)))
        )
        self.correction_offsets = (
            np.asarray(correction_offsets, dtype=np.float64)
            if correction_offsets is not None
            else np.zeros((0, 2))
        )
        if self.correction_features.size:
            correction_model = np.zeros_like(self.correction_features)
            correction_model[:, list(MODEL_FEATURE_INDICES)] = (
                self.correction_features[:, list(MODEL_FEATURE_INDICES)]
            )
            self._correction_scaled = (
                correction_model - self.raw_mean
            ) / self.raw_std
        else:
            self._correction_scaled = np.zeros(
                (0, len(FEATURE_NAMES)), dtype=np.float64
            )
        self.pose_correction = pose_correction
        self.pose_weight = float(pose_weight)
        self.pose_alpha = float(pose_alpha)
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
        corrections: int = 0,
        correction_features: np.ndarray | None = None,
        correction_offsets: np.ndarray | None = None,
        motion_samples: np.ndarray | None = None,
        motion_targets: np.ndarray | None = None,
        motion_point_ids: np.ndarray | None = None,
        motion_poses: np.ndarray | None = None,
        pose_alpha: float = 0.0,
        pose_weight: float = 0.0,
        pose_correction: PoseCorrection | None = None,
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
        samples, targets, point_ids, _ = _cap_samples(
            samples, targets, point_ids
        )
        unique_points = np.unique(point_ids)

        # Fit the gaze mapping on eye-in-head features only.  The head/face
        # features stay in ``samples`` for diagnostics and for future models.
        model_samples = np.zeros_like(samples)
        model_samples[:, list(MODEL_FEATURE_INDICES)] = samples[
            :, list(MODEL_FEATURE_INDICES)
        ]

        raw_mean, raw_std, raw_scaled = _standardize(model_samples)
        expanded = expand_matrix(model_samples)
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

        # Optional global head-pose correction.  The calibration window selects
        # pose_weight/pose_alpha on held-out points.  Motion samples are the
        # same targets observed while the user deliberately moves their head;
        # they give the correction its pose variation.
        pose_weight_value = 0.0
        pose_alpha_value = 0.0
        extra_samples: np.ndarray | None = None
        if pose_correction is not None and pose_weight > 0.0:
            pose_weight_value = float(pose_weight)
            pose_alpha_value = float(pose_alpha)
        elif pose_weight > 0.0:
            motion_ok = (
                motion_samples is not None
                and motion_targets is not None
                and motion_point_ids is not None
                and motion_poses is not None
            )
            if motion_ok:
                motion_values = np.asarray(motion_samples, dtype=np.float64)
                motion_y = np.asarray(motion_targets, dtype=np.float64)
                motion_ids = np.asarray(
                    motion_point_ids, dtype=np.int64
                ).reshape(-1)
                motion_pose_values = np.asarray(
                    motion_poses, dtype=np.float64
                )
                if (
                    motion_values.ndim == 2
                    and motion_values.shape[1] == len(FEATURE_NAMES)
                    and motion_y.shape == (motion_values.shape[0], 2)
                    and motion_ids.size == motion_values.shape[0]
                    and motion_pose_values.shape
                    == (motion_values.shape[0], len(HEAD_POSE_FEATURES))
                    and np.all(np.isfinite(motion_values))
                    and np.all(np.isfinite(motion_pose_values))
                ):
                    (
                        motion_values,
                        motion_y,
                        motion_ids,
                        motion_pose_values,
                    ) = _cap_samples(
                        motion_values,
                        motion_y,
                        motion_ids,
                        motion_pose_values,
                    )
                    motion_model = np.zeros_like(motion_values)
                    motion_model[:, list(MODEL_FEATURE_INDICES)] = (
                        motion_values[:, list(MODEL_FEATURE_INDICES)]
                    )
                    motion_raw_scaled = (
                        motion_model - raw_mean
                    ) / raw_std
                    motion_scaled = (
                        expand_matrix(motion_model) - mean
                    ) / std
                    base_motion = motion_scaled @ coef + intercept
                    if krr_weight > 0.0 and krr_coef is not None:
                        kernel_motion = _rbf_matrix(
                            motion_raw_scaled, raw_scaled, krr_gamma
                        )
                        residual_motion = kernel_motion @ krr_coef
                        if krr_residual_limit > 0.0:
                            residual_motion = np.clip(
                                residual_motion,
                                -krr_residual_limit,
                                krr_residual_limit,
                            )
                        base_motion = (
                            base_motion + krr_weight * residual_motion
                        )
                    selected_alpha = (
                        float(pose_alpha) if pose_alpha > 0 else 10.0
                    )
                    pose_correction = fit_pose_correction(
                        motion_pose_values,
                        motion_y - base_motion,
                        selected_alpha,
                    )
                    pose_weight_value = float(pose_weight)
                    pose_alpha_value = selected_alpha
                    extra_samples = motion_model
                # invalid motion data simply disables the correction

        worst = float(np.sqrt(max(selected_per_point.values(), default=0.0)))

        # Clip unseen inputs with a modest extrapolation allowance so a bad
        # blink or an extreme head position cannot send the lens flying.
        clip_source = (
            np.vstack([model_samples, extra_samples])
            if extra_samples is not None
            else model_samples
        )
        raw_range = np.maximum(
            clip_source.max(axis=0) - clip_source.min(axis=0), 1e-6
        )
        clip_low = clip_source.min(axis=0) - 0.20 * raw_range
        clip_high = clip_source.max(axis=0) + 0.20 * raw_range

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
            corrections=int(corrections),
            pose_weight=pose_weight_value,
            pose_alpha=pose_alpha_value,
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
            correction_features=correction_features,
            correction_offsets=correction_offsets,
            pose_correction=pose_correction,
            pose_weight=pose_weight_value,
            pose_alpha=pose_alpha_value,
        )

    # -------------------------------------------------------------- predict
    def _predict_base(
        self, raw: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Polynomial + kernel prediction before mouse corrections."""
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
        return out, raw_scaled

    def _correction_offset(self, raw_scaled: np.ndarray) -> np.ndarray:
        if not self._correction_scaled.size:
            return np.zeros(2, dtype=np.float64)
        distance_sq = np.sum(
            np.square(self._correction_scaled - raw_scaled), axis=1
        )
        weights = np.exp(-_CORRECTION_GAMMA * distance_sq)
        # Squaring the kernel and dropping negligible weights makes the
        # nearest correction dominate instead of being diluted by many
        # unrelated corrections elsewhere on the screen.
        weights = np.where(
            weights >= _CORRECTION_MIN_WEIGHT, weights * weights, 0.0
        )
        total = float(np.sum(weights))
        if total < 1e-9:
            return np.zeros(2, dtype=np.float64)
        return (weights @ self.correction_offsets) / total

    def predict(
        self, values: np.ndarray, head_pose: np.ndarray | None = None
    ) -> GazePrediction:
        raw = np.asarray(values, dtype=np.float64).reshape(-1)
        if raw.size != len(FEATURE_NAMES):
            raise ValueError(f"expected {len(FEATURE_NAMES)} features")
        raw = select_model_features(raw)
        raw = np.clip(raw, self.clip_low, self.clip_high)
        out, raw_scaled = self._predict_base(raw)
        if (
            self.pose_weight > 0.0
            and self.pose_correction is not None
            and head_pose is not None
        ):
            out = out + self.pose_weight * self.pose_correction.apply(head_pose)
        out = out + self._correction_offset(raw_scaled)
        return GazePrediction(float(out[0]), float(out[1]))

    def predict_unclipped(self, values: np.ndarray) -> GazePrediction:
        """Predict without the feature clipping, used for pose-motion fitting."""
        raw = np.asarray(values, dtype=np.float64).reshape(-1)
        if raw.size != len(FEATURE_NAMES):
            raise ValueError(f"expected {len(FEATURE_NAMES)} features")
        raw = select_model_features(raw)
        out, raw_scaled = self._predict_base(raw)
        out = out + self._correction_offset(raw_scaled)
        return GazePrediction(float(out[0]), float(out[1]))

    # ------------------------------------------------------ mouse correction
    def with_correction(
        self,
        features: np.ndarray,
        target: tuple[float, float],
        head_pose: np.ndarray | None = None,
    ) -> GazeModel:
        """Return a new model with a mouse-drag correction added.

        Corrections are a small local residual memory on top of the fitted
        model: each drag stores ``target - base_prediction`` at the gaze
        features where the user released the lens.  Prediction blends nearby
        corrections with an RBF weight, so the correction is applied where the
        user made it and decays away from that region.

        This is O(number of corrections) work, not a full refit, so it feels
        immediate.  A correction near an older one replaces the older one
        rather than compounding.
        """
        raw = np.asarray(features, dtype=np.float64).reshape(-1)
        if raw.size != len(FEATURE_NAMES):
            raise ValueError("correction features have the wrong shape")
        if not np.all(np.isfinite(raw)):
            raise ValueError("correction features contain non-finite values")
        target_values = np.asarray(target, dtype=np.float64).reshape(-1)
        if target_values.size != 2 or not np.all(np.isfinite(target_values)):
            raise ValueError("correction target has the wrong shape")

        raw_full = raw
        raw = select_model_features(raw)
        clip_low = np.minimum(self.clip_low, raw)
        clip_high = np.maximum(self.clip_high, raw)
        raw = np.clip(raw, clip_low, clip_high)
        base, raw_scaled = self._predict_base(raw)
        if (
            self.pose_weight > 0.0
            and self.pose_correction is not None
            and head_pose is not None
        ):
            base = base + self.pose_weight * self.pose_correction.apply(
                head_pose
            )
        offset = target_values - base

        kept_features = self.correction_features
        kept_offsets = self.correction_offsets
        if self._correction_scaled.size:
            distance_sq = np.sum(
                np.square(self._correction_scaled - raw_scaled), axis=1
            )
            similarity = np.exp(-_CORRECTION_GAMMA * distance_sq)
            keep = similarity < _CORRECTION_SIMILARITY
            kept_features = self.correction_features[keep]
            kept_offsets = self.correction_offsets[keep]

        correction_features = np.vstack(
            [kept_features, raw_full.reshape(1, -1)]
        )
        correction_offsets = np.vstack([kept_offsets, offset.reshape(1, -1)])
        if correction_features.shape[0] > _MAX_CORRECTIONS:
            correction_features = correction_features[-_MAX_CORRECTIONS:]
            correction_offsets = correction_offsets[-_MAX_CORRECTIONS:]

        metrics = CalibrationMetrics(
            train_rmse=self.metrics.train_rmse,
            loo_rmse=self.metrics.loo_rmse,
            n_points=self.metrics.n_points,
            n_samples=self.metrics.n_samples,
            alpha=self.metrics.alpha,
            worst_point_rmse=self.metrics.worst_point_rmse,
            validation_rmse=self.metrics.validation_rmse,
            validation_points=self.metrics.validation_points,
            krr_gamma=self.metrics.krr_gamma,
            krr_alpha=self.metrics.krr_alpha,
            krr_weight=self.metrics.krr_weight,
            corrections=self.metrics.corrections + 1,
        )
        return GazeModel(
            raw_mean=self.raw_mean,
            raw_std=self.raw_std,
            mean=self.mean,
            std=self.std,
            coef=self.coef,
            intercept=self.intercept,
            clip_low=clip_low,
            clip_high=clip_high,
            openness_threshold=self.openness_threshold,
            screen=self.screen,
            metrics=metrics,
            samples=self.samples,
            targets=self.targets,
            point_ids=self.point_ids,
            krr_train=self.krr_train,
            krr_coef=self.krr_coef,
            krr_gamma=self.krr_gamma,
            krr_weight=self.krr_weight,
            krr_residual_limit=self.krr_residual_limit,
            correction_features=correction_features,
            correction_offsets=correction_offsets,
            pose_correction=self.pose_correction,
            pose_weight=self.pose_weight,
            pose_alpha=self.pose_alpha,
            created_at=self.created_at,
        )

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
        text = f"{self.quality_label} · ±{self.error_rmse:.0f} px"
        if self.metrics.corrections:
            count = self.metrics.corrections
            text += f" · {count} {'fix' if count == 1 else 'fixes'}"
        if self.metrics.pose_weight > 0:
            text += " · head pose"
        return text

    # ------------------------------------------------------------------- io
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": MODEL_VERSION,
            "feature_version": FEATURE_VERSION,
            "model_mode": MODEL_MODE,
            "created_at": self.created_at,
            "screen": self.screen,
            "openness_threshold": self.openness_threshold,
            "clip_low": self.clip_low.tolist(),
            "clip_high": self.clip_high.tolist(),
            "pose_correction": (
                {
                    "mean": self.pose_correction.mean.tolist(),
                    "std": self.pose_correction.std.tolist(),
                    "coef": self.pose_correction.coef.tolist(),
                    "intercept": self.pose_correction.intercept.tolist(),
                    "clip_low": self.pose_correction.clip_low.tolist(),
                    "clip_high": self.pose_correction.clip_high.tolist(),
                    "limit": self.pose_correction.limit,
                }
                if self.pose_correction is not None
                else None
            ),
            "pose_alpha": self.pose_alpha,
            "pose_weight": self.pose_weight,
            "metrics": self.metrics.to_dict(),
            "samples": self.samples.tolist(),
            "targets": self.targets.tolist(),
            "point_ids": self.point_ids.tolist(),
            "corrections": [
                {"features": features.tolist(), "offset": offset.tolist()}
                for features, offset in zip(
                    self.correction_features,
                    self.correction_offsets,
                    strict=True,
                )
            ],
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
            pose_alpha = float(raw.get("pose_alpha", 0.0))
            pose_weight = float(raw.get("pose_weight", 0.0))
            had_pose = pose_weight > 0.0
            pose_correction = None
            pose_items = raw.get("pose_correction")
            if isinstance(pose_items, dict):
                mean = np.asarray(pose_items["mean"], dtype=np.float64)
                std = np.asarray(pose_items["std"], dtype=np.float64)
                coef = np.asarray(pose_items["coef"], dtype=np.float64)
                intercept = np.asarray(
                    pose_items["intercept"], dtype=np.float64
                )
                clip_low = np.asarray(
                    pose_items["clip_low"], dtype=np.float64
                )
                clip_high = np.asarray(
                    pose_items["clip_high"], dtype=np.float64
                )
                if (
                    mean.shape == (len(HEAD_POSE_FEATURES),)
                    and std.shape == mean.shape
                    and coef.shape == (len(HEAD_POSE_FEATURES), 2)
                    and intercept.shape == (2,)
                    and clip_low.shape == mean.shape
                    and clip_high.shape == mean.shape
                ):
                    pose_correction = PoseCorrection(
                        mean=mean,
                        std=std,
                        coef=coef,
                        intercept=intercept,
                        clip_low=clip_low,
                        clip_high=clip_high,
                        limit=float(pose_items.get("limit", 0.0)),
                    )
                else:
                    pose_weight = 0.0
            if had_pose and pose_correction is None:
                # Old pose calibration (v0.7) without the reusable correction
                # record.  Reject it so the user recalibrates with the
                # stable-motion protocol instead of using a stale model.
                return None
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
            corrections = (
                int(metrics.get("corrections", 0))
                if isinstance(metrics, dict)
                else 0
            )
            old_model = str(raw.get("model_mode", "")) != MODEL_MODE
            if old_model:
                # Saved before the eye-only model.  Its held-out number no
                # longer describes the refitted model; report the fresh LOO
                # estimate instead of a stale validation error.  Its drag
                # corrections were relative to the old all-feature base and
                # cannot be reused safely.
                validation = 0.0
                validation_points = 0
                corrections = 0
                correction_items = []
                pose_correction = None
                pose_weight = 0.0
                pose_alpha = 0.0
            else:
                correction_items = raw.get("corrections", [])
            correction_features = None
            correction_offsets = None
            if isinstance(correction_items, list) and correction_items:
                correction_features = np.asarray(
                    [item["features"] for item in correction_items],
                    dtype=np.float64,
                )
                correction_offsets = np.asarray(
                    [item["offset"] for item in correction_items],
                    dtype=np.float64,
                )
                if (
                    correction_features.ndim != 2
                    or correction_features.shape[1] != len(FEATURE_NAMES)
                    or correction_offsets.shape != (correction_features.shape[0], 2)
                ):
                    raise ValueError("saved corrections have the wrong shape")
            model = cls.fit(
                samples=samples,
                targets=targets,
                point_ids=point_ids,
                openness_threshold=float(raw.get("openness_threshold", 0.1)),
                screen=dict(raw.get("screen", {})),
                validation_rmse=validation,
                validation_points=validation_points,
                corrections=corrections,
                correction_features=correction_features,
                correction_offsets=correction_offsets,
                pose_correction=pose_correction,
                pose_weight=pose_weight,
                pose_alpha=pose_alpha,
            )
            saved_clip_low = raw.get("clip_low")
            saved_clip_high = raw.get("clip_high")
            if saved_clip_low is not None and saved_clip_high is not None:
                clip_low = np.asarray(saved_clip_low, dtype=np.float64)
                clip_high = np.asarray(saved_clip_high, dtype=np.float64)
                if (
                    clip_low.shape == model.clip_low.shape
                    and clip_high.shape == model.clip_high.shape
                ):
                    model.clip_low = clip_low
                    model.clip_high = clip_high
            model.created_at = str(raw.get("created_at", model.created_at))
            return model
        except (KeyError, TypeError, ValueError):
            return None
