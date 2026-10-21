"""The visible-video adjustment model: exposure, brightness and contrast as one linear map.

For a pixel value ``x`` in [0, 1] the adjusted value is::

    g         = 2 ** exposure_ev
    slope     = contrast * g
    intercept = 0.5 - 0.5 * contrast + brightness
    y         = clip(slope * x + intercept, 0, 1)

which equals ``clip(contrast * (g * x - 0.5) + 0.5 + brightness, 0, 1)``. The same map is applied to
R, G and B, and to luma (Y) for the analysis, because luma is a weighted sum of R, G and B whose
weights sum to 1.

The browser draws the live and played-back video with an SVG ``feComponentTransfer`` built from the
same slope and intercept (``frontend/src/lib/visibleAdjust.ts``). ``tests/fixtures/
visible_adjust_parity.json`` is read by the tests of both, so they cannot drift apart.

uint8 mapping (identical in both languages): for an input byte ``u``, ``x = u / 255`` and the
output is ``floor(y * 255 + 0.5)``, i.e. round half up. It is spelled out rather than left to
``np.round`` (round half to even) or ``Math.round`` so that Python and TypeScript agree on every
tie.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from numbers import Real
from typing import Any

import numpy as np
import numpy.typing as npt

logger = logging.getLogger(__name__)

NEUTRAL: dict[str, float] = {"exposure_ev": 0.0, "brightness": 0.0, "contrast": 1.0}
"""The identity adjustment (the default of every control)."""

LIMITS: dict[str, tuple[float, float]] = {
    "exposure_ev": (-3.0, 3.0),
    "brightness": (-0.5, 0.5),
    "contrast": (0.25, 4.0),
}
"""Inclusive ``(low, high)`` of every control."""

NEUTRAL_TOLERANCE = 1e-6
"""A control this close to its default counts as untouched. Within it the uint8 map is the
identity: the largest shift is under 1e-3 of a grey level."""


def validate_adjust(raw: Any) -> dict[str, float]:
    """Check ``raw`` and return its three numbers as floats.

    ``raw`` must be a mapping with ``exposure_ev``, ``brightness`` and ``contrast``, each a real
    number (not a bool) inside :data:`LIMITS`. Other keys, such as ``preset`` and ``based_on`` in a
    recording request, are ignored and not returned. Run values through this before
    :func:`adjust_linear` or :func:`apply_adjust`: NaN and infinity are rejected here, and
    unvalidated they behave differently in Python and TypeScript.

    Raises:
        ValueError: ``raw`` is not a mapping, a control is missing, is not a real number, is a
            bool, is not finite, or lies outside its limits.
    """
    if not isinstance(raw, Mapping):
        raise ValueError(f"visible adjustment must be an object, got {type(raw).__name__}")
    out: dict[str, float] = {}
    for key, (low, high) in LIMITS.items():
        if key not in raw:
            raise ValueError(f"visible adjustment is missing {key!r}")
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"{key} must be a number, got {type(value).__name__}")
        try:
            number = float(value)
        except OverflowError:  # an int too large for a float is out of range by definition
            raise ValueError(
                f"{key} must be between {low:g} and {high:g}, got an integer too large for a float"
            ) from None
        if not low <= number <= high:  # also false for NaN
            raise ValueError(f"{key} must be between {low:g} and {high:g}, got {number:g}")
        out[key] = number
    return out


def adjust_linear(a: Mapping[str, float]) -> tuple[float, float]:
    """Return ``(slope, intercept)`` of the adjustment on values in [0, 1]."""
    slope = a["contrast"] * 2.0 ** a["exposure_ev"]
    intercept = 0.5 - 0.5 * a["contrast"] + a["brightness"]
    return slope, intercept


def apply_adjust(u8: npt.NDArray[np.uint8], a: Mapping[str, float]) -> npt.NDArray[np.uint8]:
    """Adjust a uint8 array of any shape (luma or RGB) and return a new uint8 array.

    Every value goes through the map in the module docstring, rounded half up. The 256 possible
    inputs are mapped once and looked up, so the cost does not depend on the number of pixels.
    ``a`` must come from :func:`validate_adjust` (NaN/inf are not handled here).

    Raises:
        ValueError: ``u8`` is not a uint8 array.
    """
    if u8.dtype != np.uint8:
        raise ValueError(f"apply_adjust needs a uint8 array, got {u8.dtype}")
    slope, intercept = adjust_linear(a)
    x = np.arange(256, dtype=np.float64) / 255.0
    y = np.clip(slope * x + intercept, 0.0, 1.0)
    table = np.floor(y * 255.0 + 0.5).astype(np.uint8)
    return table[u8]


def is_neutral(a: Mapping[str, float]) -> bool:
    """True when every control is within :data:`NEUTRAL_TOLERANCE` of its default."""
    return all(
        math.isclose(a[key], NEUTRAL[key], rel_tol=0.0, abs_tol=NEUTRAL_TOLERANCE)
        for key in NEUTRAL
    )
