"""Camera controls: set object parameters / case / NUC mode / frame rate; NUC command.

Node names, units and enumerations follow what the A70 probe reported (docs/radiometry.md
§object parameters, §cases, §NUC, §frame rate): temperatures in Kelvin, humidity as a
fraction, ``NUCMode`` ∈ {Off, Automatic}, ``IRFrameRate`` ∈ {Rate60Hz … Rate4Hz}.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.camera.base import CameraBackend, CameraError, DeviceDescriptor, Frame
from flir_research_interface.camera.simulated import SimulatedCameraBackend, UniformScene


def _sim() -> SimulatedCameraBackend:
    cam = SimulatedCameraBackend(UniformScene(25.0), width=8, height=6, fps=30.0)
    cam.connect(cam.enumerate()[0])
    return cam


def test_simulated_info_exposes_cases_and_controls() -> None:
    cam = _sim()
    info = cam.camera_info()
    assert len(info["measurement_cases"]) == 3
    assert info["active_case"]["index"] == 1
    assert info["active_case"]["low_c"] == pytest.approx(-20.0)
    assert info["object_parameters"]["ObjectEmissivity"] == pytest.approx(0.95)
    assert info["object_parameters"]["ReflectedTemperature"] == pytest.approx(293.15)
    assert info["nuc_mode"] == "Automatic"
    assert info["ir_frame_rate"] == "Rate30Hz"
    assert info["enum_options"]["NUCMode"] == ["Off", "Automatic"]
    assert "Rate15Hz" in info["enum_options"]["IRFrameRate"]


def test_simulated_set_parameters_updates_info() -> None:
    cam = _sim()
    out = cam.set_parameters(
        {
            "ObjectEmissivity": 0.9,
            "ReflectedTemperature": 300.15,
            "CurrentCase": 2,
            "NUCMode": "Off",
            "IRFrameRate": "Rate15Hz",
        }
    )
    assert out["ObjectEmissivity"] == pytest.approx(0.9)
    info = cam.camera_info()
    assert info["object_parameters"]["ObjectEmissivity"] == pytest.approx(0.9)
    assert info["object_parameters"]["ReflectedTemperature"] == pytest.approx(300.15)
    assert info["active_case"]["index"] == 2
    assert info["active_case"]["high_c"] == pytest.approx(1000)
    assert info["nuc_mode"] == "Off"
    assert info["ir_frame_rate"] == "Rate15Hz"
    assert info["frame_rate_hz"] == pytest.approx(15.0)


@pytest.mark.parametrize(
    "values",
    [
        {"ObjectEmissivity": 1.5},
        {"ObjectEmissivity": "hot"},
        {"CurrentCase": 7},
        {"NUCMode": "Bogus"},
        {"IRFrameRate": "Rate1000Hz"},
        {"R": 1.0},  # calibration constants are read-only metadata
        {"NoSuchNode": 1},
    ],
)
def test_simulated_set_parameters_rejects_bad_values(values: dict[str, object]) -> None:
    cam = _sim()
    before = cam.camera_info()
    with pytest.raises(ValueError):
        cam.set_parameters(values)
    assert cam.camera_info()["object_parameters"] == before["object_parameters"]


def test_simulated_execute_nuc_counts_and_rejects_unknown() -> None:
    cam = _sim()
    cam.execute("NUCAction")
    assert cam.camera_info()["nuc_count"] == 1
    with pytest.raises(ValueError):
        cam.execute("SelfDestruct")


def test_base_backend_controls_default_to_not_supported() -> None:
    class Bare(CameraBackend):
        def enumerate(self) -> list[DeviceDescriptor]:
            return []

        def connect(self, descriptor: DeviceDescriptor) -> None:
            pass

        def disconnect(self) -> None:
            pass

        @property
        def is_connected(self) -> bool:
            return False

        def camera_info(self) -> dict[str, object]:
            return {}

        def frames(self) -> Iterator[Frame]:
            return iter(())

    with pytest.raises(CameraError):
        Bare().set_parameters({"ObjectEmissivity": 0.9})
    with pytest.raises(CameraError):
        Bare().execute("NUCAction")


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        default_backend="simulated", sim_fps=60.0, experiments_root=tmp_path, min_free_gb=0.0
    )
    return TestClient(app)


def test_parameters_endpoint_requires_connection_and_validates(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        r = c.post("/api/camera/parameters", json={"values": {"ObjectEmissivity": 0.9}})
        assert r.status_code == 409
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        bad = c.post("/api/camera/parameters", json={"values": {"ObjectEmissivity": 2}})
        assert bad.status_code == 400
        ok = c.post(
            "/api/camera/parameters", json={"values": {"ObjectEmissivity": 0.9, "CurrentCase": 0}}
        )
        assert ok.status_code == 200, ok.text
        info = c.get("/api/camera/info").json()
        assert info["object_parameters"]["ObjectEmissivity"] == pytest.approx(0.9)
        assert info["active_case"]["index"] == 0
        c.post("/api/camera/disconnect")


def test_parameters_locked_while_recording_but_nuc_allowed_and_logged(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        assert (
            c.post("/api/recording/start", json={"name": "lock", "nuc_hold": False}).status_code
            == 200
        )
        locked = c.post("/api/camera/parameters", json={"values": {"ObjectEmissivity": 0.9}})
        assert locked.status_code == 409 and "recording" in locked.json()["detail"]
        nuc = c.post("/api/camera/nuc")
        assert nuc.status_code == 200, nuc.text
        time.sleep(0.2)
        exp_dir = Path(c.get("/api/recording/status").json()["experiment_dir"])
        assert c.post("/api/recording/stop").status_code == 200
        events = json.loads((exp_dir / "events.json").read_text())
        assert any(e["type"] == "nuc" for e in events)
        assert c.get("/api/camera/info").json()["nuc_count"] == 1
        c.post("/api/camera/disconnect")
