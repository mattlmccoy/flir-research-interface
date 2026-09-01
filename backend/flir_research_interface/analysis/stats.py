"""Frame, spot and rectangle-ROI statistics on temperature arrays.

Inputs are 2-D float arrays in °C (or any unit); NaNs are ignored and counted. Coordinates are
image (x, y) = (column, row), origin top-left, matching the UI and Research Studio conventions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True)
class Spot:
    """A single pixel measurement point."""

    x: int
    y: int


@dataclass(frozen=True)
class RectangleRoi:
    """Half-open rectangle [x0, x1) x [y0, y1) in pixel coordinates."""

    x0: int
    y0: int
    x1: int
    y1: int

    def __post_init__(self) -> None:
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError(f"RectangleRoi must have x1 > x0 and y1 > y0, got {self}")

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0


def _stats(values: npt.NDArray[np.floating[Any]], x_off: int, y_off: int) -> dict[str, Any]:
    finite = np.isfinite(values)
    n = int(finite.sum())
    nan_count = int(values.size - n)
    if n == 0:
        return {
            "n": 0,
            "nan_count": nan_count,
            "min": None,
            "max": None,
            "mean": None,
            "std": None,
            "min_xy": None,
            "max_xy": None,
        }
    masked = np.where(finite, values, np.nan)
    imin = int(np.nanargmin(masked))
    imax = int(np.nanargmax(masked))
    h, w = values.shape
    return {
        "n": n,
        "nan_count": nan_count,
        "min": float(np.nanmin(masked)),
        "max": float(np.nanmax(masked)),
        "mean": float(np.nanmean(masked)),
        "std": float(np.nanstd(masked)),
        "min_xy": (imin % w + x_off, imin // w + y_off),
        "max_xy": (imax % w + x_off, imax // w + y_off),
    }


def frame_stats(field: npt.NDArray[np.floating[Any]]) -> dict[str, Any]:
    """Whole-frame min/max/mean/std with pixel positions of the extremes."""
    if field.ndim != 2:
        raise ValueError("field must be 2-D (height, width)")
    return _stats(field, 0, 0)


def spot_value(field: npt.NDArray[np.floating[Any]], spot: Spot) -> float:
    """Value at (x, y). Raises IndexError when outside the image."""
    h, w = field.shape
    if not (0 <= spot.x < w and 0 <= spot.y < h):
        raise IndexError(f"spot {spot} outside image {w}x{h}")
    return float(field[spot.y, spot.x])


def roi_stats(field: npt.NDArray[np.floating[Any]], roi: RectangleRoi) -> dict[str, Any]:
    """Statistics inside a rectangle; extreme positions are absolute image coordinates."""
    h, w = field.shape
    if roi.x1 > w or roi.y1 > h or roi.x0 < 0 or roi.y0 < 0:
        raise IndexError(f"roi {roi} outside image {w}x{h}")
    sub = field[roi.y0 : roi.y1, roi.x0 : roi.x1]
    return _stats(sub, roi.x0, roi.y0)


__all__ = ["RectangleRoi", "Spot", "frame_stats", "roi_stats", "spot_value"]
