"""Small signal-processing helpers used to stabilise gaze tracking."""

from __future__ import annotations

import math
import time


def _alpha(cutoff: float, dt: float) -> float:
    cutoff = max(1e-4, cutoff)
    dt = max(1e-4, dt)
    tau = 1.0 / (2.0 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


class OneEuroFilter:
    """The 1€ filter: adaptive low-pass with low lag on fast movements."""

    def __init__(
        self,
        min_cutoff: float = 1.0,
        beta: float = 0.02,
        derivative_cutoff: float = 1.0,
    ) -> None:
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.derivative_cutoff = float(derivative_cutoff)
        self._x: float | None = None
        self._dx = 0.0
        self._t: float | None = None

    def reset(self, value: float | None = None) -> None:
        self._x = value
        self._dx = 0.0
        self._t = None

    def filter(self, value: float, timestamp: float | None = None) -> float:
        now = time.monotonic() if timestamp is None else float(timestamp)
        value = float(value)
        if self._x is None or self._t is None:
            self._x = value
            self._t = now
            self._dx = 0.0
            return value
        dt = max(1e-3, min(0.5, now - self._t))
        raw_dx = (value - self._x) / dt
        self._dx += _alpha(self.derivative_cutoff, dt) * (raw_dx - self._dx)
        cutoff = self.min_cutoff + self.beta * abs(self._dx)
        self._x += _alpha(cutoff, dt) * (value - self._x)
        self._t = now
        return self._x


class PointFilter:
    """2D wrapper around :class:`OneEuroFilter`."""

    def __init__(
        self,
        min_cutoff: float = 1.0,
        beta: float = 0.02,
        derivative_cutoff: float = 1.0,
    ) -> None:
        self.x = OneEuroFilter(min_cutoff, beta, derivative_cutoff)
        self.y = OneEuroFilter(min_cutoff, beta, derivative_cutoff)

    def configure(self, min_cutoff: float, beta: float = 0.02) -> None:
        self.x.min_cutoff = float(min_cutoff)
        self.y.min_cutoff = float(min_cutoff)
        self.x.beta = float(beta)
        self.y.beta = float(beta)

    def reset(self, point: tuple[float, float] | None = None) -> None:
        if point is None:
            self.x.reset()
            self.y.reset()
        else:
            self.x.reset(point[0])
            self.y.reset(point[1])

    def filter(
        self, point: tuple[float, float], timestamp: float | None = None
    ) -> tuple[float, float]:
        return (
            self.x.filter(point[0], timestamp),
            self.y.filter(point[1], timestamp),
        )
