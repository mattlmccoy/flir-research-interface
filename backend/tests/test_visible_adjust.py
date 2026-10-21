"""The visible-video adjustment model (exposure, brightness, contrast).

``fixtures/visible_adjust_parity.json`` holds one real 126-pixel luma row of
``20261020_144402_Run`` (frame 6141) and, for nine settings, the slope/intercept and uint8 output
the spec formula gives. ``frontend/src/lib/visibleAdjust.test.ts`` reads the same file, so the
browser filter and the Python applier are held to one table.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from flir_research_interface.analysis.visible_adjust import (
    LIMITS,
    NEUTRAL,
    adjust_linear,
    apply_adjust,
    is_neutral,
    validate_adjust,
)

_PARITY = json.loads(
    (Path(__file__).parent / "fixtures" / "visible_adjust_parity.json").read_text()
)
_LUMA = np.array(_PARITY["luma"], dtype=np.uint8)


def test_parity_fixture_has_the_real_row_and_every_limit() -> None:
    assert _LUMA.shape == (126,)
    names = {c["name"] for c in _PARITY["cases"]}
    assert {"neutral", "exposure_min", "exposure_max", "brightness_min", "brightness_max",
            "contrast_min", "contrast_max"} <= names
    assert len(_PARITY["cases"]) == 9


@pytest.mark.parametrize("case", _PARITY["cases"], ids=lambda c: c["name"])
def test_parity_table(case: dict[str, Any]) -> None:
    slope, intercept = adjust_linear(case["adjust"])
    assert slope == pytest.approx(case["slope"], abs=1e-12)
    assert intercept == pytest.approx(case["intercept"], abs=1e-12)
    out = apply_adjust(_LUMA, case["adjust"])
    assert out.dtype == np.uint8
    assert out.tolist() == case["expected"]


def test_neutral_is_identity_on_real_row() -> None:
    assert apply_adjust(_LUMA, NEUTRAL).tolist() == _LUMA.tolist()
    assert adjust_linear(NEUTRAL) == (1.0, 0.0)


def test_neutral_is_identity_on_every_uint8_value() -> None:
    every = np.arange(256, dtype=np.uint8)
    assert apply_adjust(every, NEUTRAL).tolist() == every.tolist()


def test_apply_keeps_shape_and_dtype() -> None:
    a = {"exposure_ev": 1.0, "brightness": 0.1, "contrast": 1.2}
    for shape in [(126,), (6, 7), (4, 5, 3), (2, 4, 5, 3)]:
        u8 = np.random.default_rng(0).integers(0, 256, size=shape, dtype=np.uint8)
        out = apply_adjust(u8, a)
        assert out.shape == shape
        assert out.dtype == np.uint8
        assert u8.dtype == np.uint8  # input untouched


def test_apply_does_not_modify_its_input() -> None:
    u8 = _LUMA.copy()
    apply_adjust(u8, {"exposure_ev": -2.0, "brightness": 0.3, "contrast": 3.0})
    assert u8.tolist() == _LUMA.tolist()


def test_apply_rejects_non_uint8() -> None:
    with pytest.raises(ValueError, match="uint8"):
        apply_adjust(np.zeros(4, dtype=np.float32), NEUTRAL)


def test_apply_matches_the_scalar_formula_for_every_input_value() -> None:
    a = {"exposure_ev": 0.7, "brightness": -0.13, "contrast": 1.9}
    slope, intercept = adjust_linear(a)
    got = apply_adjust(np.arange(256, dtype=np.uint8), a).tolist()
    want = [int(np.floor(min(1.0, max(0.0, slope * (u / 255.0) + intercept)) * 255.0 + 0.5))
            for u in range(256)]
    assert got == want


def test_apply_rounds_exact_ties_half_up() -> None:
    # one stop down halves the value: 1, 3, 5, 7, 255 give y * 255 = 0.5, 1.5, 2.5, 3.5, 127.5
    # exactly; round-half-to-even (np.round) would give 0, 2, 2, 4, 128
    got = apply_adjust(
        np.array([1, 3, 5, 7, 255], dtype=np.uint8),
        {"exposure_ev": -1.0, "brightness": 0.0, "contrast": 1.0},
    )
    assert got.tolist() == [1, 2, 3, 4, 128]


def test_adjust_linear_matches_the_documented_formula() -> None:
    slope, intercept = adjust_linear({"exposure_ev": 2.0, "brightness": 0.25, "contrast": 0.5})
    assert slope == pytest.approx(2.0)  # 0.5 * 2**2
    assert intercept == pytest.approx(0.5)  # 0.5 - 0.25 + 0.25


def test_validate_accepts_and_returns_only_the_three_numbers() -> None:
    got = validate_adjust({"exposure_ev": 1, "brightness": -0.25, "contrast": 2.5,
                           "preset": "bright room", "based_on": None})
    assert got == {"exposure_ev": 1.0, "brightness": -0.25, "contrast": 2.5}
    assert all(type(v) is float for v in got.values())


def test_validate_accepts_both_limits_of_every_control() -> None:
    for key, (lo, hi) in LIMITS.items():
        for edge in (lo, hi):
            assert validate_adjust({**NEUTRAL, key: edge})[key] == edge


@pytest.mark.parametrize(
    "bad",
    [
        {"exposure_ev": 3.0001, "brightness": 0.0, "contrast": 1.0},
        {"exposure_ev": -3.0001, "brightness": 0.0, "contrast": 1.0},
        {"exposure_ev": 0.0, "brightness": 0.5001, "contrast": 1.0},
        {"exposure_ev": 0.0, "brightness": -0.5001, "contrast": 1.0},
        {"exposure_ev": 0.0, "brightness": 0.0, "contrast": 0.2499},
        {"exposure_ev": 0.0, "brightness": 0.0, "contrast": 4.0001},
        {"exposure_ev": float("nan"), "brightness": 0.0, "contrast": 1.0},
        {"exposure_ev": float("inf"), "brightness": 0.0, "contrast": 1.0},
        {"exposure_ev": True, "brightness": 0.0, "contrast": 1.0},
        {"exposure_ev": 0.0, "brightness": False, "contrast": 1.0},
        {"exposure_ev": 0.0, "brightness": 0.0, "contrast": True},
        {"exposure_ev": "1", "brightness": 0.0, "contrast": 1.0},
        {"exposure_ev": None, "brightness": 0.0, "contrast": 1.0},
        {"exposure_ev": 0.0, "brightness": 0.0},
        {},
        None,
        [0.0, 0.0, 1.0],
        "neutral",
    ],
)
def test_validate_rejects_out_of_range_and_bool(bad: Any) -> None:
    with pytest.raises(ValueError):
        validate_adjust(bad)


def test_is_neutral() -> None:
    assert is_neutral(NEUTRAL)
    assert is_neutral({"exposure_ev": 0.0, "brightness": 0.0, "contrast": 1.0})
    assert is_neutral({"exposure_ev": 5e-7, "brightness": -5e-7, "contrast": 1.0 + 5e-7})
    assert not is_neutral({"exposure_ev": 0.01, "brightness": 0.0, "contrast": 1.0})
    assert not is_neutral({"exposure_ev": 0.0, "brightness": 0.01, "contrast": 1.0})
    assert not is_neutral({"exposure_ev": 0.0, "brightness": 0.0, "contrast": 1.01})


def test_near_neutral_values_are_identity_on_uint8() -> None:
    # is_neutral's tolerance must never hide a visible change
    a = {"exposure_ev": 1e-6, "brightness": 1e-6, "contrast": 1.0 + 1e-6}
    assert is_neutral(a)
    every = np.arange(256, dtype=np.uint8)
    assert apply_adjust(every, a).tolist() == every.tolist()


def test_defaults_and_limits_match_the_spec() -> None:
    assert NEUTRAL == {"exposure_ev": 0.0, "brightness": 0.0, "contrast": 1.0}
    assert LIMITS == {"exposure_ev": (-3.0, 3.0), "brightness": (-0.5, 0.5),
                      "contrast": (0.25, 4.0)}
