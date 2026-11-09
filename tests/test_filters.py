from __future__ import annotations

import pytest

from eyelens.gaze.filters import OneEuroFilter, PointFilter


def test_first_value_is_passed_through() -> None:
    filt = OneEuroFilter()
    assert filt.filter(42.0, timestamp=1.0) == pytest.approx(42.0)


def test_constant_signal_stays_constant() -> None:
    filt = OneEuroFilter()
    t = 0.0
    for _ in range(30):
        out = filt.filter(3.5, timestamp=t)
        assert out == pytest.approx(3.5)
        t += 1.0 / 30.0


def test_step_moves_toward_new_value_without_overshoot() -> None:
    filt = OneEuroFilter(min_cutoff=2.0, beta=0.0)
    t = 0.0
    for _ in range(10):
        filt.filter(0.0, timestamp=t)
        t += 1.0 / 30.0
    outputs = []
    for _ in range(20):
        outputs.append(filt.filter(1.0, timestamp=t))
        t += 1.0 / 30.0
    assert outputs[-1] > 0.5
    assert outputs[-1] <= 1.0 + 1e-9
    assert all(b >= a - 1e-9 for a, b in zip(outputs, outputs[1:]))


def test_point_filter() -> None:
    filt = PointFilter()
    first = filt.filter((10.0, 20.0), timestamp=1.0)
    assert first == pytest.approx((10.0, 20.0))
    filt.reset((50.0, 60.0))
    assert filt.filter((50.0, 60.0), timestamp=2.0) == pytest.approx((50.0, 60.0))
