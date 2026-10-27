"""Remove the 13.56 MHz RF banding from a thermal frame, for display and image exports only.

With RF on (before the camera riser) the A70 picks up diagonal stripes about 2.4 px apart. In the
2-D spectrum that is two broad patches (plus their conjugates), measured on 15 runs 2026-10-01..19:
around (fy, fx) = (+0.19, +0.34) cycles/px (~60 % of the excess power) and (+0.29, -0.34) (~34 %).

Each patch is *detected* on its core band: its mean power against the median power of the rest of
the fine-detail spectrum (above 0.2 cycles/px, away from the banding and from the camera's own
row/column pattern on the axes). Truly RF-off frames score <= 2.9, riser runs with RF on <= 2.5,
pre-riser runs 5..811. A detected patch is only removed when the banding it carries is at least the
camera noise (both estimated from the same frame), because removing a patch also removes the scene's
fine texture in it: below the noise that costs more than it saves (20261019_182233_Run at 150 W:
~9 mK banding vs ~28 mK noise). A removed patch goes whole over a slightly wider band, then the
frame is rebuilt. Nothing removed -> the frame comes back unchanged.

Recorded counts are never modified: callers get a new array for display. Numbers (ROI readouts,
CSVs, frame stats) must keep using the raw counts.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from flir_research_interface.radiometry.overrange import over_range_mask

Band = tuple[tuple[float, float], tuple[float, float]]
RF_BANDS: dict[str, Band] = {
    "diag+": ((0.15, 0.235), (0.29, 0.41)),
    "diag-": ((0.24, 0.32), (-0.41, -0.28)),
}
"""Core band of each patch: ((fy_lo, fy_hi), (fx_lo, fx_hi)) in cycles/px; conjugate mirrored."""
REMOVE_MARGIN = 0.04
"""A detected patch is removed over its core band widened by this much (cycles/px) on every side."""
DETECT_RATIO = 4.0
"""A patch is banding when its mean power is this many times the fine-detail floor."""


def _grid(h: int, w: int) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    fy = ((np.arange(h) - h // 2) / h)[:, None]
    fx = ((np.arange(w) - w // 2) / w)[None, :]
    return fy, fx


def _patch(
    fy: npt.NDArray[np.float64], fx: npt.NDArray[np.float64], band: Band, margin: float
) -> npt.NDArray[np.bool_]:
    (y0, y1), (x0, x1) = band
    m = (fy >= y0 - margin) & (fy < y1 + margin) & (fx >= x0 - margin) & (fx < x1 + margin)
    h, w = m.shape
    ii, jj = np.nonzero(m)
    m[(2 * (h // 2) - ii) % h, (2 * (w // 2) - jj) % w] = True  # conjugate (fftshift layout)
    return m


def rf_notch(
    counts: npt.NDArray[np.uint16], kelvin_per_count: float | None
) -> tuple[npt.NDArray[np.uint16], dict[str, Any]]:
    """Return ``(display_counts, info)``; ``info["bands"]`` lists the patches removed ([]: none)."""
    if kelvin_per_count is None:
        return counts, {"applied": False, "reason": "not temperature-linear (raw counts)"}
    k = counts.astype(np.float64) * kelvin_per_count
    over = over_range_mask(counts, kelvin_per_count=kelvin_per_count)
    work = k.copy()
    if over is not None:
        work[over] = float(k[~over].mean()) if (~over).any() else 0.0
    spec = np.fft.fftshift(np.fft.fft2(work - work.mean()))
    power = np.abs(spec) ** 2
    h, w = counts.shape
    fy, fx = _grid(h, w)
    cores = {name: _patch(fy, fx, band, 0.0) for name, band in RF_BANDS.items()}
    floor_px = (np.hypot(fy, fx) > 0.2) & (np.abs(fy) > 2 / h) & (np.abs(fx) > 2 / w)
    for m in cores.values():
        floor_px &= ~m
    floor = float(np.median(power[floor_px]))
    detected = [n for n, m in cores.items() if floor > 0 and power[m].mean() > DETECT_RATIO * floor]
    # sizes in kelvin (Parseval): white noise from the floor, banding as the patch's excess power
    n_px = counts.size
    noise_k = float(np.sqrt(floor / n_px)) if floor > 0 else 0.0
    wide = {n: _patch(fy, fx, RF_BANDS[n], REMOVE_MARGIN) for n in detected}
    size_k = {
        n: float(np.sqrt(max(0.0, float((power[m] - floor).sum())))) / n_px for n, m in wide.items()
    }
    found = [n for n in detected if size_k[n] >= noise_k]
    below = [n for n in detected if n not in found]
    sizes = {
        "banding_mk": round(max(size_k.values(), default=0.0) * 1e3, 2),
        "noise_mk": round(noise_k * 1e3, 2),
        "below_noise": below,
    }
    if not found:
        return counts, {"applied": True, "bands": [], "rms_mk": 0.0, "max_mk": 0.0, **sizes}
    kill = np.zeros(counts.shape, dtype=bool)
    for name in found:
        kill |= wide[name]
    removed = np.real(np.fft.ifft2(np.fft.ifftshift(np.where(kill, spec, 0))))
    if over is not None:
        removed[over] = 0.0
    out = np.clip(np.rint((k - removed) / kelvin_per_count), 0, 65535).astype(np.uint16)
    if over is not None:
        out[over] = counts[over]
    return out, {
        "applied": True,
        "bands": found,
        "rms_mk": round(float(removed.std()) * 1e3, 2),
        "max_mk": round(float(np.abs(removed).max()) * 1e3, 2),
        **sizes,
    }


__all__ = ["DETECT_RATIO", "REMOVE_MARGIN", "RF_BANDS", "rf_notch"]
