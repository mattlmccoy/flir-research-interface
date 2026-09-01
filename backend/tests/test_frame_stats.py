"""Tests for frame / ROI statistics used by validation mode and later by the live UI."""

from __future__ import annotations

import numpy as np
import pytest

from flir_research_interface.analysis.stats import (
    RectangleRoi,
    Spot,
    frame_stats,
    roi_stats,
    spot_value,
)


def _field() -> np.ndarray:
    # 4 rows x 6 cols, values 0..23 as float32 "temperatures"
    return np.arange(24, dtype=np.float32).reshape(4, 6)


def test_frame_stats_min_max_mean_std_and_argpositions() -> None:
    s = frame_stats(_field())
    assert s["min"] == 0.0 and s["max"] == 23.0
    assert s["mean"] == pytest.approx(11.5)
    assert s["std"] == pytest.approx(np.arange(24).std())
    assert s["min_xy"] == (0, 0) and s["max_xy"] == (5, 3)
    assert s["n"] == 24


def test_spot_value_uses_x_then_y() -> None:
    # x=2, y=1 -> row 1, col 2 -> value 8
    assert spot_value(_field(), Spot(x=2, y=1)) == 8.0


def test_spot_out_of_bounds_raises() -> None:
    with pytest.raises(IndexError):
        spot_value(_field(), Spot(x=6, y=0))


def test_rectangle_roi_is_half_open_and_reports_area() -> None:
    # x 1..3 (cols 1,2), y 0..2 (rows 0,1) -> values 1,2,7,8
    roi = RectangleRoi(x0=1, y0=0, x1=3, y1=2)
    s = roi_stats(_field(), roi)
    assert s["n"] == 4
    assert s["min"] == 1.0 and s["max"] == 8.0
    assert s["mean"] == pytest.approx(4.5)
    assert s["std"] == pytest.approx(np.std([1, 2, 7, 8]))
    assert s["min_xy"] == (1, 0) and s["max_xy"] == (2, 1)  # absolute image coords


def test_rectangle_roi_rejects_empty_or_inverted() -> None:
    with pytest.raises(ValueError):
        RectangleRoi(x0=3, y0=0, x1=3, y1=2)
    with pytest.raises(ValueError):
        RectangleRoi(x0=4, y0=0, x1=3, y1=2)


def test_stats_ignore_nan() -> None:
    f = _field()
    f[0, 0] = np.nan
    s = frame_stats(f)
    assert s["n"] == 23 and s["min"] == 1.0 and s["nan_count"] == 1
