"""Tests for the hardware-abstraction types in camera/base.py."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from flir_research_interface.camera.base import (
    CameraBackend,
    DeviceDescriptor,
    Frame,
)


def _frame(**overrides: object) -> Frame:
    kwargs: dict[str, object] = {
        "frame_id": 7,
        "device_timestamp_ns": 1_000_000_000,
        "host_timestamp_ns": 2_000_000_000,
        "pixel_format": "Mono16",
        "ir_format": "TemperatureLinear10mK",
        "counts": np.zeros((4, 6), dtype=np.uint16),
        "incomplete": False,
    }
    kwargs.update(overrides)
    return Frame(**kwargs)  # type: ignore[arg-type]


def test_frame_is_immutable() -> None:
    frame = _frame()
    with pytest.raises(dataclasses.FrozenInstanceError):
        frame.frame_id = 8  # type: ignore[misc]


def test_frame_reports_width_and_height_from_array() -> None:
    frame = _frame()
    assert frame.height == 4
    assert frame.width == 6


def test_frame_rejects_non_uint16_counts() -> None:
    with pytest.raises(TypeError, match="uint16"):
        _frame(counts=np.zeros((4, 6), dtype=np.float32))


def test_frame_rejects_non_2d_counts() -> None:
    with pytest.raises(ValueError, match="2-D"):
        _frame(counts=np.zeros((4, 6, 1), dtype=np.uint16))


def test_camera_backend_is_abstract() -> None:
    with pytest.raises(TypeError):
        CameraBackend()  # type: ignore[abstract]


def test_device_descriptor_is_immutable() -> None:
    desc = DeviceDescriptor(
        backend="simulated",
        model="Simulated A70",
        serial="SIM-0001",
        ip_address=None,
        mac_address=None,
        firmware=None,
        interface="virtual",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        desc.serial = "x"  # type: ignore[misc]
