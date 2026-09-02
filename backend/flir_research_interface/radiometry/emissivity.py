"""Per-ROI emissivity / reflected-temperature re-correction.

The camera's temperature-linear output already assumes its global ``ObjectEmissivity`` and
``ReflectedTemperature``. FLIR's signal model with a transparent atmosphere (bench distance):

    W_meas = eps * W(T_obj) + (1 - eps) * W(T_refl),    W(T) = R / (exp(B / T) - F)

``recorrect_celsius`` inverts the camera's conversion to recover ``W_meas`` per pixel, then solves
again with the ROI's own ``eps`` and ``T_refl``. ``R``, ``B``, ``F`` are the camera's calibration
constants (``metadata.json`` → ``camera.calibration_constants``). The frontend mirror is
``lib/emissivity.ts``; both are checked against the same hand-solved reference in the tests.
Atmospheric transmission is treated as 1; at 0.44 m and 50 % RH the A70 itself estimates ~1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True)
class Radiometry:
    R: float
    B: float
    F: float

    @classmethod
    def from_camera(cls, cam: dict[str, Any] | None) -> tuple[Radiometry, float, float] | None:
        """(constants, camera emissivity, camera reflected temperature K) or None if absent."""
        if not cam:
            return None
        cc = cam.get("calibration_constants") or {}
        op = cam.get("object_parameters") or {}
        try:
            r, b, f = float(cc["R"]), float(cc["B"]), float(cc["F"])
            eps, trefl = float(op["ObjectEmissivity"]), float(op["ReflectedTemperature"])
        except (KeyError, TypeError, ValueError):
            return None
        if min(r, b, f, eps, trefl) <= 0:
            return None
        return cls(r, b, f), eps, trefl


def radiance(t_k: npt.ArrayLike, rbf: Radiometry) -> npt.NDArray[np.float64]:
    t = np.asarray(t_k, dtype=np.float64)
    return rbf.R / (np.exp(rbf.B / t) - rbf.F)


def temperature_k(w: npt.ArrayLike, rbf: Radiometry) -> npt.NDArray[np.float64]:
    w_arr = np.asarray(w, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        return rbf.B / np.log(rbf.R / w_arr + rbf.F)


def recorrect_celsius(
    t_c: npt.ArrayLike,
    rbf: Radiometry,
    *,
    eps_cam: float,
    trefl_cam_k: float,
    eps: float,
    trefl_k: float,
) -> npt.NDArray[np.float64]:
    """Camera-reported °C → °C for emissivity ``eps`` and reflected temperature ``trefl_k``."""
    t = np.asarray(t_c, dtype=np.float64)
    w_meas = eps_cam * radiance(t + 273.15, rbf) + (1.0 - eps_cam) * radiance(trefl_cam_k, rbf)
    w_obj = (w_meas - (1.0 - eps) * radiance(trefl_k, rbf)) / eps
    out = temperature_k(w_obj, rbf) - 273.15
    out = np.where(w_obj > 0, out, np.nan)
    return np.where(np.isnan(t), np.nan, out)


__all__ = ["Radiometry", "radiance", "recorrect_celsius", "temperature_k"]
