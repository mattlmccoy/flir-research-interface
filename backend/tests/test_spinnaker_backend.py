"""SpinnakerCameraBackend tests.

Pure-logic tests run everywhere. Tests marked ``hardware`` need PySpin and a reachable FLIR
camera (``pytest --hardware``); they restore camera settings they change.
"""

from __future__ import annotations

import itertools
import time

import numpy as np
import pytest

from flir_research_interface.camera.base import NotConnectedError
from flir_research_interface.camera.spinnaker import (
    OBJECT_PARAMETER_NODES,
    SpinnakerCameraBackend,
    build_camera_info,
)
from flir_research_interface.radiometry.temperature_linear import IRFormat, counts_to_celsius

# ----------------------------------------------------------------------------- pure logic


def test_object_parameter_nodes_match_probe_observation() -> None:
    # Names observed on the A70 (fw 42.0.0) ObjectParameters category, 2026-09-01.
    assert set(OBJECT_PARAMETER_NODES) == {
        "ObjectEmissivity",
        "ReflectedTemperature",
        "AtmosphericTemperature",
        "ObjectDistance",
        "RelativeHumidity",
        "ExtOpticsTemperature",
        "ExtOpticsTransmission",
        "EstimatedTransmission",
        "UseWindowTemperature",
    }


def test_build_camera_info_groups_nodes_and_converts_kelvin_limits() -> None:
    raw = {
        "DeviceVendorName": "FLIR Systems",
        "DeviceModelName": "FLIR A70",
        "DeviceSerialNumber": "00000000",
        "DeviceVersion": "42.0.0",
        "LensName": "FOL08",
        "Width": 640,
        "Height": 480,
        "PixelFormat": "Mono16",
        "IRFormat": "TemperatureLinear10mK",
        "AcquisitionFrameRate": 30.0,
        "IRFrameRate": "Rate30Hz",
        "CurrentCase": 1,
        "NumCases": 3,
        "ObjectEmissivity": 0.95,
        "ReflectedTemperature": 293.15,
        "NUCMode": "Automatic",
        "GevTimestampTickFrequency": 1_000_000_000,
    }
    cases = [
        {"index": 0, "low_k": 253.15, "high_k": 448.15},
        {"index": 1, "low_k": 253.15, "high_k": 523.15},
    ]
    info = build_camera_info(
        raw, cases=cases, spinnaker_version="4.4.0.246", ir_format_before="Radiometric"
    )
    assert info["backend"] == "spinnaker"
    assert info["model"] == "FLIR A70" and info["lens"] == "FOL08"
    assert (
        info["ir_format"] == "TemperatureLinear10mK"
        and info["ir_format_before_connect"] == "Radiometric"
    )
    assert info["object_parameters"]["ObjectEmissivity"] == 0.95
    assert info["measurement_cases"][1]["low_c"] == pytest.approx(-20.0)
    assert info["measurement_cases"][1]["high_c"] == pytest.approx(250.0)
    assert info["active_case"]["index"] == 1
    assert info["spinnaker_version"] == "4.4.0.246"
    assert info["timestamp_tick_hz"] == 1_000_000_000


def test_frames_before_connect_raises() -> None:
    cam = SpinnakerCameraBackend()
    with pytest.raises(NotConnectedError):
        next(cam.frames())


# ----------------------------------------------------------------------------- hardware

pytestmark_hw = pytest.mark.hardware


@pytest.mark.hardware
def test_enumerate_finds_a_flir_camera() -> None:
    with SpinnakerCameraBackend() as cam:
        devices = cam.enumerate()
    assert devices, "no camera visible to Spinnaker"
    assert devices[0].backend == "spinnaker"
    assert "FLIR" in (devices[0].model or "")
    assert devices[0].ip_address and devices[0].ip_address.count(".") == 3


@pytest.mark.hardware
def test_connect_streams_temperature_linear_frames_and_restores_format() -> None:
    cam = SpinnakerCameraBackend(ir_format=IRFormat.TEMPERATURE_LINEAR_10MK)
    desc = cam.enumerate()[0]
    cam.connect(desc)
    try:
        info = cam.camera_info()
        before = info["ir_format_before_connect"]
        assert info["ir_format"] == "TemperatureLinear10mK"
        assert info["pixel_format"] == "Mono16"
        assert (
            info["measurement_cases"]
            and info["active_case"]["high_c"] > info["active_case"]["low_c"]
        )
        assert set(OBJECT_PARAMETER_NODES) <= set(info["object_parameters"])

        t0 = time.monotonic()
        frames = list(itertools.islice(cam.frames(), 10))
        elapsed = time.monotonic() - t0
        assert len(frames) == 10
        ids = [f.frame_id for f in frames]
        assert ids == sorted(ids) and len(set(ids)) == 10
        for f in frames:
            assert f.counts.shape == (480, 640) and f.counts.dtype == np.uint16
            assert f.ir_format == "TemperatureLinear10mK" and f.pixel_format == "Mono16"
            assert not f.incomplete
        dts = np.diff([f.device_timestamp_ns for f in frames]) / 1e6
        assert 20 < np.median(dts) < 50, f"frame period ms: {dts}"  # ~33 ms at 30 Hz
        assert elapsed < 5.0
        c = counts_to_celsius(frames[-1].counts, IRFormat.TEMPERATURE_LINEAR_10MK)
        assert -20 < float(c[240, 320]) < 100, "implausible room-scene temperature"
        stats = cam.stream_stats()
        assert {"lost", "dropped", "incomplete", "delivered"} <= set(stats)
    finally:
        cam.disconnect()
    # Reconnect without reconfiguring: the format must be what it was before the first connect.
    check = SpinnakerCameraBackend(ir_format=None)
    check.connect(check.enumerate()[0])
    try:
        assert check.camera_info()["ir_format"] == before
    finally:
        check.disconnect()
