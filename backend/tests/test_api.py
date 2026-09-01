"""API tests against the simulated camera (FastAPI TestClient, no hardware)."""

from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.api.frames import decode_frame_message, encode_frame_message
from flir_research_interface.camera.base import Frame


def _client() -> TestClient:
    app = create_app(default_backend="simulated", sim_fps=60.0, viz_fps=30.0)
    return TestClient(app)


def test_health_and_version() -> None:
    with _client() as c:
        r = c.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok" and "version" in body


def test_setup_sdk_endpoint_reports_platform_selection() -> None:
    with _client() as c:
        r = c.get("/api/setup/sdk")
        assert r.status_code == 200
        body = r.json()
        assert {"system", "machine", "python_tag", "pyspin_importable"} <= set(body)


def test_camera_lifecycle_over_rest() -> None:
    with _client() as c:
        st = c.get("/api/camera/status").json()
        assert st["state"] == "disconnected"
        devs = c.get("/api/camera/devices").json()
        assert devs and devs[0]["backend"] == "simulated"
        r = c.post(
            "/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]}
        )
        assert r.status_code == 200, r.text
        assert c.get("/api/camera/status").json()["state"] == "acquiring"
        info = c.get("/api/camera/info").json()
        assert info["ir_format"] == "TemperatureLinear10mK" and info["pixel_format"] == "Mono16"
        r = c.post("/api/camera/disconnect")
        assert r.status_code == 200
        assert c.get("/api/camera/status").json()["state"] == "disconnected"


def test_connect_unknown_backend_is_400() -> None:
    with _client() as c:
        r = c.post("/api/camera/connect", json={"backend": "nope"})
        assert r.status_code == 400


def test_frame_message_roundtrip_preserves_raw_counts() -> None:
    counts = (np.arange(6, dtype=np.uint16) * 1000 + 29815).reshape(2, 3)
    frame = Frame(
        frame_id=9,
        device_timestamp_ns=5,
        host_timestamp_ns=6,
        pixel_format="Mono16",
        ir_format="TemperatureLinear10mK",
        counts=counts,
        incomplete=False,
    )
    msg = encode_frame_message(frame, stats={"camera_fps": 30.0, "viz_dropped": 2})
    header, data = decode_frame_message(msg)
    assert header["frame_id"] == 9 and header["width"] == 3 and header["height"] == 2
    assert header["dtype"] == "uint16" and header["byte_order"] == "little"
    assert header["kelvin_per_count"] == 0.01 and header["kelvin_offset"] == 273.15
    assert header["center_c"] is not None and header["min_c"] < header["max_c"]
    assert header["camera_fps"] == 30.0
    np.testing.assert_array_equal(data, counts)


def test_websocket_streams_frames_with_binary_payload() -> None:
    with _client() as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        with c.websocket_connect("/ws/frames") as ws:
            msg = ws.receive_bytes()
            header, data = decode_frame_message(msg)
            assert header["width"] == 640 and header["height"] == 480
            assert data.dtype == np.uint16 and data.shape == (480, 640)
            msg2 = ws.receive_bytes()
            header2, _ = decode_frame_message(msg2)
            assert header2["frame_id"] > header["frame_id"]
        c.post("/api/camera/disconnect")
