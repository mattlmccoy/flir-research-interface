"""256-entry RGB lookup tables for the export/media palettes.

The live viewer offers many palettes; the export compositor mirrors the common ones here. ``iron``
and ``inferno`` use the exact tables already in the codebase; the others are built by interpolating
a handful of colour stops (close enough for a thermal viewing palette). ``palette_lut(name)`` always
returns a (256, 3) uint8 LUT, falling back to inferno for an unknown name.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from flir_research_interface.analysis.preview import IRON_LUT
from flir_research_interface.radiometry.colormaps import INFERNO_LUT

# (position 0..1, R, G, B) stops, dark (cold) → bright (hot).
_STOPS: dict[str, list[tuple[float, int, int, int]]] = {
    "grayscale": [(0, 0, 0, 0), (1, 255, 255, 255)],
    "blackhot": [(0, 255, 255, 255), (1, 0, 0, 0)],
    "magma": [(0, 0, 0, 4), (0.25, 80, 18, 123), (0.5, 182, 54, 121),
              (0.75, 251, 136, 97), (1, 252, 253, 191)],
    "plasma": [(0, 13, 8, 135), (0.25, 126, 3, 168), (0.5, 204, 71, 120),
               (0.75, 248, 149, 64), (1, 240, 249, 33)],
    "viridis": [(0, 68, 1, 84), (0.25, 59, 82, 139), (0.5, 33, 145, 140),
                (0.75, 94, 201, 98), (1, 253, 231, 37)],
    "turbo": [(0, 48, 18, 59), (0.13, 70, 134, 251), (0.35, 42, 224, 182), (0.5, 163, 254, 74),
              (0.65, 254, 196, 55), (0.85, 232, 71, 20), (1, 122, 4, 3)],
    "rainbow": [(0, 0, 0, 255), (0.25, 0, 255, 255), (0.5, 0, 255, 0),
                (0.75, 255, 255, 0), (1, 255, 0, 0)],
}

PALETTE_NAMES = ("inferno", "iron", "magma", "plasma", "viridis", "turbo",
                 "rainbow", "grayscale", "blackhot")


def _from_stops(stops: list[tuple[float, int, int, int]]) -> npt.NDArray[np.uint8]:
    xs = np.array([s[0] for s in stops], dtype=np.float64)
    t = np.linspace(0, 1, 256)
    lut = np.zeros((256, 3), dtype=np.uint8)
    for c in range(3):
        ys = np.array([s[c + 1] for s in stops], dtype=np.float64)
        lut[:, c] = np.clip(np.rint(np.interp(t, xs, ys)), 0, 255).astype(np.uint8)
    return lut


_CACHE: dict[str, npt.NDArray[np.uint8]] = {}


def palette_lut(name: str) -> npt.NDArray[np.uint8]:
    """A (256, 3) uint8 LUT for ``name`` (inferno for anything unknown)."""
    if name == "iron":
        return IRON_LUT
    if name in ("inferno", "", None):
        return INFERNO_LUT
    if name not in _CACHE:
        stops = _STOPS.get(name)
        _CACHE[name] = _from_stops(stops) if stops else INFERNO_LUT
    return _CACHE[name]


def apply_lut(values: npt.NDArray[np.float32], vmin: float, vmax: float,
              lut: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint8]:
    """Map a °C array to RGB through ``lut`` over [vmin, vmax]; NaN → vmin, flat span → mid-LUT."""
    v = np.nan_to_num(values, nan=vmin)
    span = vmax - vmin
    if span <= 0:
        idx = np.full(v.shape, 128, dtype=np.uint8)
    else:
        idx = np.clip(np.rint((v - vmin) * (255.0 / span)), 0, 255).astype(np.uint8)
    return lut[idx]


__all__ = ["PALETTE_NAMES", "palette_lut", "apply_lut"]
