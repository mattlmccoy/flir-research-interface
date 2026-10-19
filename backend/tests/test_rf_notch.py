"""The 13.56 MHz banding filter (display / image exports only; recorded counts are never touched).

Fixtures are real A70 frames (TemperatureLinear10mK, 10 mK per count) from
tests/fixtures/rf_banding_frames.npz: 20261019_120320_Run (before the camera riser) at a frame
with the RF generator off (``pre_riser_rf_off``, plus the next frame for the noise floor) and one
~5 s later with RF on (``pre_riser_rf_on``, heavy diagonal banding), and 20261019_131145_Run (on the
riser) with RF on (``riser_rf_on``, banding below the camera noise).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from flir_research_interface.analysis.rf_notch import rf_notch

K = 0.01  # kelvin per count (TemperatureLinear10mK)
FX = np.load(Path(__file__).parent / "fixtures" / "rf_banding_frames.npz")


def _kelvin(c: np.ndarray) -> np.ndarray:
    return c.astype(np.float64) * K


def _fine_detail_mk(c: np.ndarray) -> float:
    """RMS above 0.1 cycles/px: the banding plus the scene's fine texture and the noise."""
    a = _kelvin(c)
    s = np.fft.fftshift(np.fft.fft2(a - a.mean()))
    h, w = a.shape
    fy = ((np.arange(h) - h // 2) / h)[:, None]
    fx = ((np.arange(w) - w // 2) / w)[None, :]
    keep = np.where(np.hypot(fy, fx) > 0.1, s, 0)
    return float(np.real(np.fft.ifft2(np.fft.ifftshift(keep))).std() * 1e3)


def _lowpass(a: np.ndarray, sigma: float = 3.0) -> np.ndarray:
    """Gaussian low-pass: keeps the scene, suppresses a ~2.4 px pattern by ~1000x."""
    x = np.arange(-int(4 * sigma), int(4 * sigma) + 1)
    k = np.exp(-(x**2) / (2 * sigma**2))
    k /= k.sum()
    a = np.apply_along_axis(lambda v: np.convolve(v, k, mode="same"), 0, a)
    return np.apply_along_axis(lambda v: np.convolve(v, k, mode="same"), 1, a)


def test_rf_off_frames_change_by_less_than_the_camera_noise() -> None:
    raw = FX["pre_riser_rf_off"]
    noise = (_kelvin(FX["pre_riser_rf_off_next"]) - _kelvin(raw)).std()
    out, info = rf_notch(raw, K)
    change = np.abs(_kelvin(out) - _kelvin(raw)).max()
    assert change < 0.025 and change < noise
    assert info["applied"] is True and info["bands"] == []  # "no RF banding found"


def test_pre_riser_banding_is_removed() -> None:
    raw = FX["pre_riser_rf_on"]
    out, info = rf_notch(raw, K)
    assert len(info["bands"]) == 2 and info["rms_mk"] > 100
    before, after = _fine_detail_mk(raw), _fine_detail_mk(out)
    clean = _fine_detail_mk(FX["pre_riser_rf_off"])  # same scene ~5 s earlier, RF off
    assert after < before / 2.5
    assert after < 2 * clean
    removed = _kelvin(raw) - _kelvin(out)
    assert abs(removed.std() * 1e3 - info["rms_mk"]) < 2  # reported size matches what was taken out


def test_the_scene_is_untouched_at_low_spatial_frequencies() -> None:
    raw = FX["pre_riser_rf_on"]
    out, _ = rf_notch(raw, K)
    smooth_diff = _lowpass(_kelvin(out) - _kelvin(raw))[12:-12, 12:-12]
    assert np.abs(smooth_diff).max() < 0.005


def test_riser_frames_with_banding_below_the_noise_are_left_alone() -> None:
    raw = FX["riser_rf_on"]
    out, info = rf_notch(raw, K)
    assert info["bands"] == []
    assert np.array_equal(out, raw)


def test_input_is_not_modified_and_the_output_has_the_same_shape_and_type() -> None:
    raw = FX["pre_riser_rf_on"].copy()
    out, _ = rf_notch(raw, K)
    assert np.array_equal(raw, FX["pre_riser_rf_on"])
    assert out.shape == raw.shape and out.dtype == np.uint16


def test_over_range_pixels_are_left_alone() -> None:
    raw = FX["pre_riser_rf_on"].copy()
    raw[10:20, 10:20] = 65535  # saturated / wrapped
    out, _ = rf_notch(raw, K)
    assert np.all(out[10:20, 10:20] == 65535)


def test_frames_that_are_not_temperature_linear_pass_through() -> None:
    raw = FX["pre_riser_rf_on"]
    out, info = rf_notch(raw, None)
    assert np.array_equal(out, raw)
    assert info["applied"] is False and "temperature" in info["reason"]
