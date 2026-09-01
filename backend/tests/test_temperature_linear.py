"""Tests for the FLIR temperature-linear counts -> temperature conversion.

Evidence for the expected values (see docs/radiometry.md):
- FLIR KB "How do I configure my camera to stream a temperature linear signal":
  TemperatureLinear 10 mK -> multiply signal by 0.01 (Kelvin); "Signal of 50000 will
  correspond to 500 Kelvin". 100 mK -> multiply by 0.1.
- FLIR gige_example_A400_A700.py: (image_data * 0.01) - 273.15 for 10 mK.
"""

from __future__ import annotations

import numpy as np
import pytest

from flir_research_interface.radiometry.temperature_linear import (
    IRFormat,
    counts_to_celsius,
    counts_to_kelvin,
)


def test_10mk_50000_counts_is_500_kelvin() -> None:
    counts = np.array([[50000]], dtype=np.uint16)
    kelvin = counts_to_kelvin(counts, IRFormat.TEMPERATURE_LINEAR_10MK)
    assert kelvin.dtype == np.float32
    assert kelvin[0, 0] == pytest.approx(500.0)


def test_10mk_room_temperature_in_celsius() -> None:
    # 29315 counts * 0.01 K = 293.15 K = 20.00 degC
    counts = np.full((2, 3), 29315, dtype=np.uint16)
    celsius = counts_to_celsius(counts, IRFormat.TEMPERATURE_LINEAR_10MK)
    assert celsius.shape == (2, 3)
    assert celsius.dtype == np.float32
    np.testing.assert_allclose(celsius, 20.0, atol=1e-3)


def test_100mk_scale() -> None:
    # 4731 counts * 0.1 K = 473.1 K = 199.95 degC
    counts = np.array([[4731]], dtype=np.uint16)
    celsius = counts_to_celsius(counts, IRFormat.TEMPERATURE_LINEAR_100MK)
    assert celsius[0, 0] == pytest.approx(199.95, abs=1e-3)


def test_radiometric_format_is_rejected() -> None:
    # Radiometric (signal-linear) counts need FLIR's calibration constants; refuse.
    counts = np.array([[1000]], dtype=np.uint16)
    with pytest.raises(ValueError, match="Radiometric"):
        counts_to_celsius(counts, IRFormat.RADIOMETRIC)


def test_input_is_not_mutated() -> None:
    counts = np.array([[29315, 30000]], dtype=np.uint16)
    before = counts.copy()
    counts_to_celsius(counts, IRFormat.TEMPERATURE_LINEAR_10MK)
    np.testing.assert_array_equal(counts, before)


def test_irformat_genicam_names_match_flir_example() -> None:
    # Exact enumeration entry strings used by FLIR's gige_example_A400_A700.py
    assert IRFormat.TEMPERATURE_LINEAR_10MK.value == "TemperatureLinear10mK"
    assert IRFormat.TEMPERATURE_LINEAR_100MK.value == "TemperatureLinear100mK"
    assert IRFormat.RADIOMETRIC.value == "Radiometric"
