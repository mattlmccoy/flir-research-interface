"""FLIR temperature-linear counts -> temperature conversion.

This module implements ONLY the conversion that FLIR documents for cameras streaming
in ``IRFormat = TemperatureLinear10mK`` / ``TemperatureLinear100mK`` with
``PixelFormat = Mono16``. In that mode the camera itself applies its factory calibration
and the object parameters (emissivity, reflected temperature, ...) and emits a 16-bit
value that is linear in Kelvin:

    TemperatureLinear10mK :  T[K] = counts * 0.01
    TemperatureLinear100mK:  T[K] = counts * 0.1

Sources (see docs/radiometry.md for full citations):
- FLIR KB "How do I configure my camera to stream a temperature linear signal?"
  ("Signal of 50000 will correspond to 500 Kelvin").
- FLIR KB 1021 "Temperature Linear Mode" (conversion happens on the camera).
- FLIR example ``gige_example_A400_A700.py`` (KB 4186): ``(image_data * 0.01) - 273.15``.

The ``Radiometric`` (signal-linear) format is deliberately NOT converted here. Doing so
requires the camera's calibration constants and FLIR's thermography formula; that path is
out of scope until it can be validated against FLIR Research Studio.
"""

from __future__ import annotations

from enum import Enum

import numpy as np
import numpy.typing as npt

KELVIN_OFFSET: float = 273.15
"""0 degC expressed in Kelvin."""


class IRFormat(str, Enum):
    """GenICam ``IRFormat`` enumeration entries, spelled exactly as FLIR's example uses them."""

    TEMPERATURE_LINEAR_10MK = "TemperatureLinear10mK"
    TEMPERATURE_LINEAR_100MK = "TemperatureLinear100mK"
    RADIOMETRIC = "Radiometric"


_KELVIN_PER_COUNT: dict[IRFormat, float] = {
    IRFormat.TEMPERATURE_LINEAR_10MK: 0.01,
    IRFormat.TEMPERATURE_LINEAR_100MK: 0.1,
}


def kelvin_per_count(ir_format: IRFormat) -> float:
    """Return the FLIR-documented Kelvin-per-count scale for a temperature-linear format.

    Raises:
        ValueError: if ``ir_format`` is not a temperature-linear format.
    """
    try:
        return _KELVIN_PER_COUNT[ir_format]
    except KeyError:
        raise ValueError(
            f"IRFormat {ir_format.value!r} is not temperature-linear; "
            "Radiometric (signal-linear) counts cannot be converted without FLIR "
            "calibration constants and are not supported."
        ) from None


def counts_to_kelvin(
    counts: npt.NDArray[np.uint16], ir_format: IRFormat
) -> npt.NDArray[np.float32]:
    """Convert temperature-linear Mono16 counts to Kelvin (float32). Input is not modified."""
    scale = kelvin_per_count(ir_format)
    return (counts.astype(np.float32) * np.float32(scale)).astype(np.float32)


def counts_to_celsius(
    counts: npt.NDArray[np.uint16], ir_format: IRFormat
) -> npt.NDArray[np.float32]:
    """Convert temperature-linear Mono16 counts to degrees Celsius (float32)."""
    kelvin = counts_to_kelvin(counts, ir_format)
    return (kelvin - np.float32(KELVIN_OFFSET)).astype(np.float32)


__all__ = [
    "KELVIN_OFFSET",
    "IRFormat",
    "counts_to_celsius",
    "counts_to_kelvin",
    "kelvin_per_count",
]
