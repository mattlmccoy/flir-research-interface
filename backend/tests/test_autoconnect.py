"""Operator auto-connect: keeps retrying while no camera is connected, never fights a user
disconnect. Driven through the SIMULATED backend - tests must never auto-connect real hardware
(PySpin crashes natively under many TestClients; see camera-resilience notes)."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flir_research_interface.api import app as app_module
from flir_research_interface.api.app import create_app


def _wait(pred: Callable[[], bool], timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def _state(client: TestClient) -> str:
    return str(client.get("/api/camera/status").json()["state"])


def _app(tmp_path: Path):  # type: ignore[no-untyped-def]
    return create_app(
        experiments_root=tmp_path, autoconnect=True, autoconnect_backend="simulated",
        autoconnect_interval_s=0.05,
    )


@pytest.fixture
def camera_appears_late(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """The camera is absent for the first two scans (unplugged / wrong subnet), then shows up."""
    calls = {"enumerate": 0}
    real = app_module._make_backend

    def fake(name: str, *, sim_fps: float):  # type: ignore[no-untyped-def]
        cam = real(name, sim_fps=sim_fps)
        orig = cam.enumerate

        def enumerate_():  # type: ignore[no-untyped-def]
            calls["enumerate"] += 1
            return [] if calls["enumerate"] <= 2 else orig()

        cam.enumerate = enumerate_  # type: ignore[method-assign]
        return cam

    monkeypatch.setattr(app_module, "_make_backend", fake)
    return calls


def test_autoconnect_keeps_retrying_until_the_camera_appears(
    tmp_path: Path, camera_appears_late: dict[str, int]
) -> None:
    with TestClient(_app(tmp_path)) as client:
        assert _wait(lambda: _state(client) == "acquiring"), _state(client)
        assert camera_appears_late["enumerate"] >= 3


def test_user_disconnect_is_not_undone_by_autoconnect(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        assert _wait(lambda: _state(client) == "acquiring")
        client.post("/api/camera/disconnect")
        time.sleep(0.4)  # many retry intervals
        assert _state(client) == "disconnected"


def test_manual_connect_rearms_autoconnect(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        assert _wait(lambda: _state(client) == "acquiring")
        client.post("/api/camera/disconnect")
        r = client.post("/api/camera/connect", json={"backend": "simulated"})
        assert r.status_code == 200, r.text
        assert client.app.state.autoconnect_paused is False  # type: ignore[attr-defined]


def test_autoconnect_off_by_default(tmp_path: Path) -> None:
    with TestClient(create_app(experiments_root=tmp_path)) as client:
        time.sleep(0.2)
        assert _state(client) == "disconnected"
