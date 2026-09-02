"""Acquisition service: owns the camera thread and a newest-wins visualization slot.

Design (brief §16, §27): the camera thread never blocks on a consumer. Visualization reads the
*latest* frame; frames replaced before anyone read them are counted in ``viz_dropped`` (this is
expected and is not a camera drop). Recording (Milestone 4) will attach a separate bounded
queue with priority; it is not implemented here.
"""

from __future__ import annotations

import enum
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from flir_research_interface.camera.base import CameraBackend, DeviceDescriptor, Frame

logger = logging.getLogger(__name__)


class ServiceState(str, enum.Enum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    ACQUIRING = "acquiring"
    ERROR = "error"


class AcquisitionService:
    """Single-camera acquisition with explicit state and counters."""

    def __init__(self, backend: CameraBackend, *, fps_window: int = 30) -> None:
        self._backend = backend
        self._state = ServiceState.DISCONNECTED
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._thread: threading.Thread | None = None
        self._stop_evt = threading.Event()
        self._latest: Frame | None = None
        self._latest_consumed = True
        self._frames_received = 0
        self._viz_dropped = 0
        self._last_error: str | None = None
        self._ts_window: deque[int] = deque(maxlen=fps_window)
        self._device: DeviceDescriptor | None = None
        self._listeners: list[Callable[[Frame], None]] = []

    # -- state ---------------------------------------------------------------------------

    @property
    def state(self) -> ServiceState:
        return self._state

    @property
    def backend(self) -> CameraBackend:
        return self._backend

    @property
    def device(self) -> DeviceDescriptor | None:
        return self._device

    # -- lifecycle -----------------------------------------------------------------------

    def enumerate(self) -> list[DeviceDescriptor]:
        return self._backend.enumerate()

    def connect(self, descriptor: DeviceDescriptor) -> None:
        self._backend.connect(descriptor)
        self._device = descriptor
        with self._lock:
            self._state = ServiceState.CONNECTED
            self._last_error = None
        logger.info("connected to %s %s", descriptor.model, descriptor.serial)

    def start(self) -> None:
        if self._state not in (ServiceState.CONNECTED, ServiceState.ERROR):
            raise RuntimeError(f"cannot start acquisition in state {self._state.value}")
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._run, name="camera-acquisition", daemon=True)
        with self._lock:
            self._state = ServiceState.ACQUIRING
        self._thread.start()
        logger.info("acquisition started")

    def stop(self) -> None:
        self._stop_evt.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=5.0)
        self._thread = None
        with self._lock:
            if self._state == ServiceState.ACQUIRING:
                self._state = ServiceState.CONNECTED
            self._cond.notify_all()
        logger.info("acquisition stopped")

    def disconnect(self) -> None:
        self.stop()
        try:
            self._backend.disconnect()
        finally:
            self._device = None
            with self._lock:
                self._state = ServiceState.DISCONNECTED
                self._cond.notify_all()

    # -- consumers -----------------------------------------------------------------------

    def add_listener(self, fn: Callable[[Frame], None]) -> None:
        """Synchronous per-frame callback (used later by the recorder). Must be fast."""
        self._listeners.append(fn)

    def remove_listener(self, fn: Callable[[Frame], None]) -> None:
        with self._lock:
            self._listeners = [f for f in self._listeners if f is not fn]

    def latest(self) -> Frame | None:
        with self._lock:
            self._latest_consumed = True
            return self._latest

    def wait_for_frame(self, *, after_id: int | None, timeout_s: float) -> Frame | None:
        """Block until a frame with id > ``after_id`` exists (or timeout); marks it consumed."""
        deadline = time.monotonic() + timeout_s
        with self._cond:
            while True:
                f = self._latest
                if f is not None and (after_id is None or f.frame_id > after_id):
                    self._latest_consumed = True
                    return f
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._state != ServiceState.ACQUIRING:
                    return None
                self._cond.wait(remaining)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            fps = None
            if len(self._ts_window) >= 2:
                span_ns = self._ts_window[-1] - self._ts_window[0]
                if span_ns > 0:
                    fps = (len(self._ts_window) - 1) * 1e9 / span_ns
            return {
                "state": self._state.value,
                "frames_received": self._frames_received,
                "viz_dropped": self._viz_dropped,
                "camera_fps": fps,
                "last_error": self._last_error,
                "latest_frame_id": self._latest.frame_id if self._latest else None,
            }

    # -- camera thread -------------------------------------------------------------------

    def _run(self) -> None:
        try:
            for frame in self._backend.frames():
                if self._stop_evt.is_set():
                    break
                for fn in self._listeners:
                    try:
                        fn(frame)
                    except Exception:  # noqa: BLE001 - a listener must not kill acquisition
                        logger.exception("frame listener failed")
                with self._cond:
                    if self._latest is not None and not self._latest_consumed:
                        self._viz_dropped += 1
                    self._latest = frame
                    self._latest_consumed = False
                    self._frames_received += 1
                    self._ts_window.append(frame.device_timestamp_ns)
                    self._cond.notify_all()
        except Exception as exc:  # noqa: BLE001 - surface any backend failure as ERROR state
            logger.exception("acquisition thread failed")
            with self._cond:
                self._last_error = f"{type(exc).__name__}: {exc}"
                self._state = ServiceState.ERROR
                self._cond.notify_all()
            return
        with self._cond:
            if self._state == ServiceState.ACQUIRING:
                self._state = ServiceState.CONNECTED
            self._cond.notify_all()


__all__ = ["AcquisitionService", "ServiceState"]
