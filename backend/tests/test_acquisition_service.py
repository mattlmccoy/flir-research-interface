"""Tests for the acquisition service (camera thread + newest-wins visualization slot)."""

from __future__ import annotations

import time

import pytest

from flir_research_interface.acquisition.service import AcquisitionService, ServiceState
from flir_research_interface.camera.simulated import SimulatedCameraBackend, UniformScene


def _service(fps: float = 200.0) -> AcquisitionService:
    cam = SimulatedCameraBackend(
        scene=UniformScene(25.0), width=32, height=24, fps=fps, realtime=True
    )
    return AcquisitionService(cam)


def _wait(pred, timeout_s: float = 2.0) -> bool:  # type: ignore[no-untyped-def]
    t_end = time.monotonic() + timeout_s
    while time.monotonic() < t_end:
        if pred():
            return True
        time.sleep(0.005)
    return False


def test_initial_state_is_disconnected() -> None:
    svc = _service()
    assert svc.state == ServiceState.DISCONNECTED
    assert svc.latest() is None
    assert svc.stats()["frames_received"] == 0


def test_connect_start_stop_disconnect_lifecycle() -> None:
    svc = _service()
    devices = svc.enumerate()
    assert devices and devices[0].backend == "simulated"
    svc.connect(devices[0])
    assert svc.state == ServiceState.CONNECTED
    svc.start()
    assert _wait(lambda: svc.stats()["frames_received"] >= 5)
    assert svc.state == ServiceState.ACQUIRING
    svc.stop()
    assert svc.state == ServiceState.CONNECTED
    svc.disconnect()
    assert svc.state == ServiceState.DISCONNECTED


def test_latest_frame_is_newest_and_viz_drops_are_counted() -> None:
    svc = _service(fps=400.0)
    svc.connect(svc.enumerate()[0])
    svc.start()
    try:
        assert _wait(lambda: svc.stats()["frames_received"] >= 40)
        a = svc.latest()
        time.sleep(0.05)
        b = svc.latest()
        assert a is not None and b is not None and b.frame_id > a.frame_id
        st = svc.stats()
        # we consumed only 2 frames of >= 40 -> most were replaced unread
        assert st["viz_dropped"] >= st["frames_received"] - 10
        assert st["camera_fps"] is not None and 300 < st["camera_fps"] < 500
    finally:
        svc.disconnect()


def test_wait_for_frame_blocks_until_a_new_frame_arrives() -> None:
    svc = _service(fps=100.0)
    svc.connect(svc.enumerate()[0])
    svc.start()
    try:
        f1 = svc.wait_for_frame(after_id=None, timeout_s=1.0)
        assert f1 is not None
        f2 = svc.wait_for_frame(after_id=f1.frame_id, timeout_s=1.0)
        assert f2 is not None and f2.frame_id > f1.frame_id
    finally:
        svc.disconnect()


def test_start_without_connect_raises() -> None:
    svc = _service()
    with pytest.raises(RuntimeError):
        svc.start()


def test_camera_error_moves_to_error_state() -> None:
    class Broken(SimulatedCameraBackend):
        def frames(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    svc = AcquisitionService(Broken(scene=UniformScene(25.0), width=8, height=8))
    svc.connect(svc.enumerate()[0])
    svc.start()
    assert _wait(lambda: svc.state == ServiceState.ERROR)
    assert "boom" in (svc.stats()["last_error"] or "")
    svc.disconnect()


class _Flaky(SimulatedCameraBackend):
    """Simulated backend whose frames() raises the first ``fail_times`` calls, then streams."""

    def __init__(self, *, fail_times: int, **kw) -> None:  # type: ignore[no-untyped-def]
        super().__init__(scene=UniformScene(25.0), width=8, height=8, fps=200.0,
                         realtime=True, **kw)
        self._fail_left = fail_times

    def frames(self):  # type: ignore[no-untyped-def]
        if self._fail_left > 0:
            self._fail_left -= 1
            raise RuntimeError("camera dropped")
        yield from super().frames()


def test_auto_reconnect_recovers_after_a_transient_drop() -> None:
    svc = AcquisitionService(
        _Flaky(fail_times=2), auto_reconnect=True, reconnect_delays=(0.01,),
    )
    svc.connect(svc.enumerate()[0])
    svc.start()
    # after two failed attempts it reconnects and streams again
    assert _wait(lambda: svc.state == ServiceState.ACQUIRING and svc.stats()["frames_received"] > 0)
    svc.disconnect()


def test_auto_reconnect_gives_up_after_max_attempts() -> None:
    class Broken(SimulatedCameraBackend):
        def frames(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    svc = AcquisitionService(
        Broken(scene=UniformScene(25.0), width=8, height=8),
        auto_reconnect=True, reconnect_delays=(0.01,), max_reconnect_attempts=2,
    )
    svc.connect(svc.enumerate()[0])
    svc.start()
    assert _wait(lambda: svc.state == ServiceState.ERROR)
    assert "gave up" in (svc.stats()["last_error"] or "")
    svc.disconnect()


def test_stall_detection_forces_a_reconnect() -> None:
    import threading as _t

    class _Stalls(SimulatedCameraBackend):
        """Yields one frame then blocks; disconnect() releases the block so frames() ends."""

        def __init__(self, **kw) -> None:  # type: ignore[no-untyped-def]
            super().__init__(scene=UniformScene(25.0), width=8, height=8, fps=200.0, **kw)
            self._release = _t.Event()

        def frames(self):  # type: ignore[no-untyped-def]
            it = super().frames()
            yield next(it)               # one real frame
            self._release.wait(2.0)      # then stall until disconnect() releases us
            self._release.clear()

        def disconnect(self) -> None:
            self._release.set()
            super().disconnect()

    svc = AcquisitionService(
        _Stalls(), auto_reconnect=True, stall_timeout_s=0.15, reconnect_delays=(0.01,),
    )
    svc.connect(svc.enumerate()[0])
    svc.start()
    # recovered after the stall was detected and the stream reconnected
    assert _wait(lambda: svc.stats()["frames_received"] >= 2, timeout_s=4.0)
    svc.disconnect()


def test_connect_retries_with_backoff_before_failing() -> None:
    class _HardToConnect(SimulatedCameraBackend):
        def __init__(self, *, fail_times: int, **kw) -> None:  # type: ignore[no-untyped-def]
            super().__init__(scene=UniformScene(25.0), width=8, height=8, **kw)
            self._fail_left = fail_times

        def connect(self, descriptor) -> None:  # type: ignore[no-untyped-def]
            if self._fail_left > 0:
                self._fail_left -= 1
                raise RuntimeError("not ready")
            super().connect(descriptor)

    cam = _HardToConnect(fail_times=2)
    svc = AcquisitionService(cam, connect_retries=3, reconnect_delays=(0.01,))
    svc.connect(svc.enumerate()[0])  # must retry past the two failures, not raise
    assert svc.state == ServiceState.CONNECTED
    svc.disconnect()
