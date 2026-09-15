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
    RECONNECTING = "reconnecting"  # lost the camera mid-stream; retrying with backoff
    ERROR = "error"


#: Backoff between reconnect attempts (seconds), capped at the last value.
_RECONNECT_DELAYS = (1.0, 2.0, 5.0, 10.0, 20.0, 30.0)


class AcquisitionService:
    """Single-camera acquisition with explicit state and counters.

    With ``auto_reconnect`` the acquisition thread supervises the stream: if the camera errors or
    stalls (no frame for ``stall_timeout_s``), it disconnects, waits with backoff, reconnects the
    same device, and resumes — surfacing ``RECONNECTING`` so the UI shows the self-healing. Default
    off, so the bare service keeps its simple connect→acquire→error semantics.
    """

    def __init__(
        self,
        backend: CameraBackend,
        *,
        fps_window: int = 30,
        auto_reconnect: bool = False,
        stall_timeout_s: float = 10.0,
        reconnect_delays: tuple[float, ...] = _RECONNECT_DELAYS,
        max_reconnect_attempts: int | None = None,
        connect_retries: int = 0,
    ) -> None:
        self._backend = backend
        self._state = ServiceState.DISCONNECTED
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._thread: threading.Thread | None = None
        self._watchdog: threading.Thread | None = None
        self._stop_evt = threading.Event()
        self._latest: Frame | None = None
        self._latest_consumed = True
        self._frames_received = 0
        self._viz_dropped = 0
        self._last_error: str | None = None
        self._ts_window: deque[int] = deque(maxlen=fps_window)
        self._device: DeviceDescriptor | None = None
        self._listeners: list[Callable[[Frame], None]] = []
        self._auto_reconnect = auto_reconnect
        self._stall_timeout_s = stall_timeout_s
        self._reconnect_delays = reconnect_delays or (1.0,)
        self._max_reconnect_attempts = max_reconnect_attempts
        self._connect_retries = connect_retries
        self._last_frame_at = 0.0

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
        # Retry the initial connect a few times: a just-powered GigE camera often isn't ready on the
        # first GVCP round-trip. The last failure is raised so a truly-absent camera still errors.
        attempts = self._connect_retries + 1
        for i in range(attempts):
            try:
                self._backend.connect(descriptor)
                break
            except Exception as exc:  # noqa: BLE001 - retry transient connect failures
                if i + 1 >= attempts:
                    raise
                delay = self._reconnect_delays[min(i, len(self._reconnect_delays) - 1)]
                logger.warning("connect attempt %d/%d failed (%s); retrying in %.1fs",
                               i + 1, attempts, exc, delay)
                if self._stop_evt.wait(delay):
                    raise
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
        self._last_frame_at = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="camera-acquisition", daemon=True)
        with self._lock:
            self._state = ServiceState.ACQUIRING
        self._thread.start()
        if self._auto_reconnect and self._stall_timeout_s > 0:
            self._watchdog = threading.Thread(
                target=self._watchdog_loop, name="camera-watchdog", daemon=True
            )
            self._watchdog.start()
        logger.info("acquisition started")

    def stop(self) -> None:
        self._stop_evt.set()
        for t in (self._thread, self._watchdog):
            if t is not None and t.is_alive() and t is not threading.current_thread():
                t.join(timeout=6.0)
        self._thread = None
        self._watchdog = None
        with self._lock:
            if self._state in (ServiceState.ACQUIRING, ServiceState.RECONNECTING):
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

    def _set_state(self, state: ServiceState, error: str | None = None) -> None:
        with self._cond:
            self._state = state
            if error is not None:
                self._last_error = error
            elif state == ServiceState.ACQUIRING:
                self._last_error = None
            self._cond.notify_all()

    def _acquire_frames(self) -> int:
        """Pump frames from the backend until stopped or the stream ends/errors. Returns the number
        of frames delivered (0 means the camera never produced one this attempt)."""
        n = 0
        for frame in self._backend.frames():
            if self._stop_evt.is_set():
                break
            self._last_frame_at = time.monotonic()
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
            n += 1
        return n

    def _run(self) -> None:
        # Supervise the stream. Without auto_reconnect this is a single pass that surfaces any
        # failure as ERROR (unchanged behaviour). With it, a failure/stall triggers a backoff +
        # reconnect of the same camera, retrying until it returns (or max attempts).
        attempt = 0
        while not self._stop_evt.is_set():
            reason: str | None = None
            try:
                if self._acquire_frames() > 0:
                    attempt = 0  # frames flowed → the connection is healthy again
                if self._stop_evt.is_set():
                    break
                reason = "camera stream ended"
            except Exception as exc:  # noqa: BLE001 - any backend failure is a candidate to recover
                logger.exception("acquisition failed")
                reason = f"{type(exc).__name__}: {exc}"

            if self._stop_evt.is_set():
                break
            if not self._auto_reconnect:
                self._set_state(ServiceState.ERROR, reason)
                return
            attempt += 1
            if self._max_reconnect_attempts is not None and attempt > self._max_reconnect_attempts:
                self._set_state(
                    ServiceState.ERROR, f"gave up after {self._max_reconnect_attempts} "
                    f"reconnect attempts: {reason}")
                return
            delay = self._reconnect_delays[min(attempt - 1, len(self._reconnect_delays) - 1)]
            self._set_state(ServiceState.RECONNECTING, f"{reason}; reconnecting in {delay:.0f}s")
            if self._stop_evt.wait(delay):
                break
            try:
                try:
                    self._backend.disconnect()
                except Exception:  # noqa: BLE001 - a lost camera may already be gone
                    pass
                if self._device is not None:
                    self._backend.connect(self._device)
                self._last_frame_at = time.monotonic()
                self._set_state(ServiceState.ACQUIRING)
            except Exception as exc:  # noqa: BLE001 - reconnect failed; loop retries with backoff
                self._set_state(ServiceState.RECONNECTING, f"reconnect failed: {exc}")

        with self._cond:
            if self._state in (ServiceState.ACQUIRING, ServiceState.RECONNECTING):
                self._state = ServiceState.CONNECTED
            self._cond.notify_all()

    def _watchdog_loop(self) -> None:
        # A stalled GigE stream blocks in ``frames()`` without raising, so nothing above notices.
        # Detect "no frame for stall_timeout_s while acquiring" and break the stream by
        # disconnecting the backend — the supervisor then reconnects.
        poll = min(self._stall_timeout_s / 2, 1.0)
        while not self._stop_evt.wait(poll):
            with self._lock:
                acquiring = self._state == ServiceState.ACQUIRING
            if acquiring and (time.monotonic() - self._last_frame_at) > self._stall_timeout_s:
                logger.warning("camera stalled (no frame for %.1fs); forcing reconnect",
                               self._stall_timeout_s)
                self._last_frame_at = time.monotonic()  # avoid re-firing before the reconnect
                try:
                    self._backend.disconnect()  # unblock the frames() generator
                except Exception:  # noqa: BLE001
                    pass


__all__ = ["AcquisitionService", "ServiceState"]
