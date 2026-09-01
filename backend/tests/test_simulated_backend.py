"""Tests for SimulatedCameraBackend (development without hardware)."""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from flir_research_interface.camera import create_backend
from flir_research_interface.camera.base import NotConnectedError
from flir_research_interface.camera.simulated import (
    GradientScene,
    HotspotRampScene,
    SimulatedCameraBackend,
    UniformScene,
)
from flir_research_interface.radiometry.temperature_linear import IRFormat, counts_to_celsius

W, H = 64, 48


def _fixed_clock() -> int:
    return 1_700_000_000_000_000_000


def _connected(scene: object, **kw: object) -> SimulatedCameraBackend:
    cam = SimulatedCameraBackend(scene=scene, width=W, height=H, fps=30.0, clock=_fixed_clock, **kw)  # type: ignore[arg-type]
    cam.connect(cam.enumerate()[0])
    return cam


def test_enumerate_reports_one_virtual_device() -> None:
    cam = SimulatedCameraBackend(scene=UniformScene(25.0), width=W, height=H)
    devices = cam.enumerate()
    assert len(devices) == 1
    assert devices[0].backend == "simulated"
    assert devices[0].serial == "SIM-0001"
    assert devices[0].interface == "virtual"


def test_frames_requires_connection() -> None:
    cam = SimulatedCameraBackend(scene=UniformScene(25.0), width=W, height=H)
    assert cam.is_connected is False
    with pytest.raises(NotConnectedError):
        next(cam.frames())


def test_connect_and_disconnect_are_tracked_and_idempotent() -> None:
    cam = _connected(UniformScene(25.0))
    assert cam.is_connected is True
    cam.disconnect()
    cam.disconnect()
    assert cam.is_connected is False


def test_frame_ids_and_device_timestamps_advance_at_fps() -> None:
    cam = _connected(UniformScene(25.0))
    f0, f1, f2 = itertools.islice(cam.frames(), 3)
    assert (f0.frame_id, f1.frame_id, f2.frame_id) == (0, 1, 2)
    period_ns = round(1e9 / 30.0)
    assert f1.device_timestamp_ns - f0.device_timestamp_ns == period_ns
    assert f2.device_timestamp_ns - f1.device_timestamp_ns == period_ns
    assert f0.host_timestamp_ns == _fixed_clock()


def test_frame_geometry_and_formats() -> None:
    cam = _connected(UniformScene(25.0))
    frame = next(cam.frames())
    assert frame.counts.shape == (H, W)
    assert frame.counts.dtype == np.uint16
    assert frame.pixel_format == "Mono16"
    assert frame.ir_format == "TemperatureLinear10mK"
    assert frame.incomplete is False


def test_uniform_scene_encodes_temperature_as_10mk_kelvin_counts() -> None:
    cam = _connected(UniformScene(25.0))
    frame = next(cam.frames())
    # (25 + 273.15) K / 0.01 K per count = 29815 counts
    assert int(frame.counts.min()) == 29815
    assert int(frame.counts.max()) == 29815
    celsius = counts_to_celsius(frame.counts, IRFormat.TEMPERATURE_LINEAR_10MK)
    np.testing.assert_allclose(celsius, 25.0, atol=0.011)


def test_100mk_format_uses_coarser_scale() -> None:
    # 26.85 degC = 300.00 K exactly -> 3000 counts at 0.1 K/count (no half-count ambiguity)
    cam = _connected(UniformScene(26.85), ir_format=IRFormat.TEMPERATURE_LINEAR_100MK)
    frame = next(cam.frames())
    assert frame.ir_format == "TemperatureLinear100mK"
    assert int(frame.counts[0, 0]) == 3000


def test_gradient_scene_runs_left_to_right() -> None:
    cam = _connected(GradientScene(min_c=20.0, max_c=120.0))
    frame = next(cam.frames())
    celsius = counts_to_celsius(frame.counts, IRFormat.TEMPERATURE_LINEAR_10MK)
    assert celsius[:, 0] == pytest.approx(20.0, abs=0.011)
    assert celsius[:, -1] == pytest.approx(120.0, abs=0.011)
    assert np.all(np.diff(celsius[0, :]) >= 0)


def test_hotspot_ramp_reaches_target_after_ramp_time() -> None:
    scene = HotspotRampScene(
        background_c=25.0,
        start_c=25.0,
        end_c=200.0,
        ramp_s=60.0,
        center_xy=(W // 2, H // 2),
        radius_px=6,
    )
    cam = _connected(scene)
    frames = cam.frames()
    first = next(frames)
    # advance to t = 60 s at 30 fps -> frame index 1800
    last = next(itertools.islice(frames, 1800 - 1, None))
    assert last.frame_id == 1800
    c_first = counts_to_celsius(first.counts, IRFormat.TEMPERATURE_LINEAR_10MK)
    c_last = counts_to_celsius(last.counts, IRFormat.TEMPERATURE_LINEAR_10MK)
    cy, cx = H // 2, W // 2
    assert c_first[cy, cx] == pytest.approx(25.0, abs=0.011)
    assert c_last[cy, cx] == pytest.approx(200.0, abs=0.011)
    assert c_last[0, 0] == pytest.approx(25.0, abs=0.011)  # background untouched


def test_noise_is_deterministic_for_a_seed() -> None:
    a = _connected(UniformScene(25.0), noise_k=0.05, seed=123)
    b = _connected(UniformScene(25.0), noise_k=0.05, seed=123)
    fa, fb = next(a.frames()), next(b.frames())
    np.testing.assert_array_equal(fa.counts, fb.counts)
    assert fa.counts.std() > 0


def test_camera_info_is_auditable() -> None:
    cam = _connected(UniformScene(25.0))
    info = cam.camera_info()
    assert info["backend"] == "simulated"
    assert info["pixel_format"] == "Mono16"
    assert info["ir_format"] == "TemperatureLinear10mK"
    assert info["width"] == W and info["height"] == H
    assert info["frame_rate_hz"] == 30.0
    assert "scene" in info


def test_registry_factory_builds_simulated_backend() -> None:
    cam = create_backend("simulated", scene=UniformScene(30.0), width=W, height=H)
    assert isinstance(cam, SimulatedCameraBackend)
    with pytest.raises(KeyError):
        create_backend("does-not-exist")
