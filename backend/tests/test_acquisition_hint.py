"""The acquisition service carries a plain-language hint next to the raw last_error.

Simulated backend only (never PySpin). The error texts are the real Spinnaker messages from
tests/fixtures/neterr/spinnaker_1023_log.txt; the adapter snapshot is the live -1023 state
(en15 at /16, see test_connect_hint.py), injected so no test touches psutil or networksetup.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any

import pytest

from flir_research_interface.acquisition.service import AcquisitionService, ServiceState
from flir_research_interface.camera.simulated import SimulatedCameraBackend, UniformScene
from flir_research_interface.connect_hint import camera_error_hint
from flir_research_interface.net_diagnostics import IfaceAddr

RAW_1023 = ("Spinnaker: Spinnaker: Camera is on an adapter with conflicting IP and subnet "
            "address range. [-1023]")
RAW_1024 = "Spinnaker: Camera has been removed from the list and is no longer valid. [-1024]"
CONFLICT = ([IfaceAddr("en15", "192.168.9.1", 16), IfaceAddr("en13", "192.168.8.1", 24)],
            {"en15": "AX88179A", "en13": "USB 10/100/1000 LAN"})


class _Diagnose:
    """camera_error_hint on the injected snapshot, counting calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def __call__(self, raw: str, camera_ip: str | None) -> dict[str, Any] | None:
        self.calls.append((raw, camera_ip))
        return camera_error_hint(raw, camera_ip, snapshot=lambda: CONFLICT)


def _wait(pred, timeout_s: float = 2.0) -> bool:  # type: ignore[no-untyped-def]
    t_end = time.monotonic() + timeout_s
    while time.monotonic() < t_end:
        if pred():
            return True
        time.sleep(0.005)
    return False


class _Removed(SimulatedCameraBackend):
    """Streams nothing: the first frames() call fails like a yanked adapter, then it recovers."""

    def __init__(self, *, fail_times: int) -> None:
        super().__init__(scene=UniformScene(25.0), width=8, height=8, fps=200.0, realtime=True)
        self._fail_left = fail_times

    def frames(self):  # type: ignore[no-untyped-def]
        if self._fail_left > 0:
            self._fail_left -= 1
            raise RuntimeError(RAW_1024)
        yield from super().frames()


def test_stream_error_carries_raw_error_and_plain_hint() -> None:
    diag = _Diagnose()
    svc = AcquisitionService(_Removed(fail_times=1), diagnose=diag)
    svc.connect(svc.enumerate()[0])
    svc.start()
    assert _wait(lambda: svc.state == ServiceState.ERROR)
    st = svc.stats()
    assert RAW_1024 in (st["last_error"] or "")  # raw text kept
    assert st["last_error_hint"]["kind"] == "adapter_removed"
    assert "Anker USB-C hub" in st["last_error_hint"]["message"]
    svc.disconnect()


def test_hint_clears_once_frames_flow_again_and_is_not_computed_per_frame() -> None:
    diag = _Diagnose()
    svc = AcquisitionService(_Removed(fail_times=1), auto_reconnect=True,
                             reconnect_delays=(0.01,), diagnose=diag)
    svc.connect(svc.enumerate()[0])
    svc.start()
    assert _wait(lambda: svc.state == ServiceState.ACQUIRING
                 and svc.stats()["frames_received"] > 20)
    assert svc.stats()["last_error_hint"] is None
    n = len(diag.calls)
    assert 1 <= n <= 4  # only around the failure
    assert _wait(lambda: svc.stats()["frames_received"] > 60)
    assert len(diag.calls) == n  # healthy streaming never diagnoses
    svc.disconnect()


def test_failed_connect_records_the_hint_with_the_camera_ip() -> None:
    class _Conflict(SimulatedCameraBackend):
        def connect(self, descriptor):  # type: ignore[no-untyped-def]
            raise RuntimeError(RAW_1023)

    diag = _Diagnose()
    svc = AcquisitionService(_Conflict(scene=UniformScene(25.0), width=8, height=8),
                             connect_retries=1, reconnect_delays=(0.0,), diagnose=diag)
    dev = dataclasses.replace(svc.enumerate()[0], ip_address="192.168.8.2")
    with pytest.raises(RuntimeError):
        svc.connect(dev)
    st = svc.stats()
    assert st["last_error"] == RAW_1023
    assert st["last_error_hint"]["command"] == (
        'sudo networksetup -setmanual "AX88179A" 192.168.9.1 255.255.255.0')
    assert diag.calls == [(RAW_1023, "192.168.8.2")]  # once, after the last retry


def test_no_error_means_no_hint() -> None:
    svc = AcquisitionService(SimulatedCameraBackend(scene=UniformScene(25.0), width=8, height=8))
    assert svc.stats()["last_error_hint"] is None
