"""GET /api/camera/status explains a failed connect in plain words, for manual and auto-connect.

Simulated backend only (never PySpin): its connect is patched to raise the real Spinnaker -1023
text (tests/fixtures/neterr/spinnaker_1023_log.txt) and its device gets the camera IP. The adapter
snapshot is the live -1023 state (en15 at /16), patched in so nothing runs psutil/networksetup.
"""

from __future__ import annotations

import dataclasses
import functools
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from flir_research_interface import connect_hint
from flir_research_interface.acquisition.service import AcquisitionService
from flir_research_interface.api import app as app_module
from flir_research_interface.api.app import create_app
from flir_research_interface.camera.base import CameraError
from flir_research_interface.net_diagnostics import IfaceAddr

RAW_1023 = ("Spinnaker: Spinnaker: Camera is on an adapter with conflicting IP and subnet "
            "address range. [-1023]")
FIX = 'sudo networksetup -setmanual "AX88179A" 192.168.9.1 255.255.255.0'


def _wait(pred: Callable[[], bool], timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


@pytest.fixture
def conflict(monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    """Connect fails with -1023 while ``state["broken"]``; flip it to let the camera in."""
    state = {"broken": True}
    real = app_module._make_backend

    def fake(name: str, *, sim_fps: float):  # type: ignore[no-untyped-def]
        cam = real(name, sim_fps=sim_fps)
        orig_enum, orig_connect = cam.enumerate, cam.connect

        def enumerate_():  # type: ignore[no-untyped-def]
            return [dataclasses.replace(d, ip_address="192.168.8.2") for d in orig_enum()]

        def connect(desc):  # type: ignore[no-untyped-def]
            if state["broken"]:
                raise CameraError(RAW_1023)
            orig_connect(desc)

        cam.enumerate = enumerate_  # type: ignore[method-assign]
        cam.connect = connect  # type: ignore[method-assign]
        return cam

    snap = ([IfaceAddr("en15", "192.168.9.1", 16), IfaceAddr("en13", "192.168.8.1", 24)],
            {"en15": "AX88179A", "en13": "USB 10/100/1000 LAN"})
    monkeypatch.setattr(app_module, "_make_backend", fake)
    monkeypatch.setattr(connect_hint, "_live_snapshot", lambda: snap)
    # the operator's connect retries back off 1+2+5 s; keep the retries, drop the waits
    monkeypatch.setattr(app_module, "AcquisitionService",
                        functools.partial(AcquisitionService, reconnect_delays=(0.0,)))
    return state


def _status(client: TestClient) -> dict[str, Any]:
    out: dict[str, Any] = client.get("/api/camera/status").json()
    return out


def test_manual_connect_failure_is_explained_in_status(
    tmp_path: Path, conflict: dict[str, bool]
) -> None:
    with TestClient(create_app(experiments_root=tmp_path)) as client:
        r = client.post("/api/camera/connect", json={"backend": "simulated"})
        assert r.status_code == 500 and RAW_1023 in r.json()["detail"]
        st = _status(client)
        assert st["state"] == "disconnected"
        assert st["last_error"] == RAW_1023  # raw kept
        assert st["last_error_hint"]["command"] == FIX
        assert "AX88179A (en15) is 192.168.9.1/16" in st["last_error_hint"]["message"]

        conflict["broken"] = False  # Matt runs the command; Connect now works
        assert client.post("/api/camera/connect", json={"backend": "simulated"}).status_code == 200
        st = _status(client)
        assert st["last_error"] is None and st["last_error_hint"] is None
        client.post("/api/camera/disconnect")


def test_autoconnect_failure_is_explained_and_clears_on_success(
    tmp_path: Path, conflict: dict[str, bool]
) -> None:
    app = create_app(experiments_root=tmp_path, autoconnect=True,
                     autoconnect_backend="simulated", autoconnect_interval_s=0.05)
    with TestClient(app) as client:
        assert _wait(lambda: (_status(client).get("last_error_hint") or {}).get("command") == FIX)
        conflict["broken"] = False
        assert _wait(lambda: _status(client)["state"] == "acquiring")
        assert _status(client)["last_error_hint"] is None


def test_user_disconnect_clears_a_stale_failure(
    tmp_path: Path, conflict: dict[str, bool]
) -> None:
    with TestClient(create_app(experiments_root=tmp_path)) as client:
        client.post("/api/camera/connect", json={"backend": "simulated"})
        assert _status(client)["last_error_hint"] is not None
        client.post("/api/camera/disconnect")
        st = _status(client)
        assert st.get("last_error") is None and st.get("last_error_hint") is None
