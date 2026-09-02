"""Visible-camera recorder (Milestone 9): ffmpeg stream-copies RTSP ``/avc/ch1`` to ``visible.mp4``.

Design (docs/visible_camera.md §2): a separate subsystem that never touches the radiometric
GigE stream. No re-encode (``-c copy``); packet timestamps come from the host clock
(``-use_wallclock_as_timestamps 1``) so the video aligns with the thermal frames' host
timestamps to within network + encoder latency. A ``visible.json`` sidecar records the start
and stop host times, the redacted URL, the command and the file hash. Credentials never land
on disk or in logs.
"""

from __future__ import annotations

import enum
import hashlib
import json
import logging
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from flir_research_interface.visible.rtsp import (
    FFPROBE_CANDIDATES,
    RTSP_PATHS,
    build_rtsp_url,
    credentials,
    find_ffprobe,
    redact_url,
)

logger = logging.getLogger(__name__)

FILE_NAME = "visible.mp4"
SIDECAR_NAME = "visible.json"
SYNC_NOTE = "host clock; ffmpeg -use_wallclock_as_timestamps 1"
SOCKET_TIMEOUT_US = 5_000_000  # fail fast when the camera is unreachable
STDERR_TAIL_LINES = 30
FFMPEG_CANDIDATES = tuple(c.replace("ffprobe", "ffmpeg") for c in FFPROBE_CANDIDATES)


class VisibleState(str, enum.Enum):
    IDLE = "idle"
    RECORDING = "recording"
    ERROR = "error"


class _Proc(Protocol):
    stdin: Any
    returncode: int | None

    def poll(self) -> int | None: ...
    def wait(self, timeout: float | None = None) -> int: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...


PopenFactory = Callable[..., _Proc]


def ffmpeg_command(ffmpeg: str, url: str, out: Path) -> list[str]:
    """ffmpeg argv: TCP transport, wall-clock packet timestamps, video-only stream copy to MP4."""
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "warning",
        "-y",  # stdin stays open on purpose: 'q' is the graceful stop that finalises the MP4
        "-rtsp_transport", "tcp",
        "-timeout", str(SOCKET_TIMEOUT_US),
        "-use_wallclock_as_timestamps", "1",
        "-i", url,
        "-map", "0:v:0",
        "-an", "-dn", "-sn",
        "-c", "copy",
        "-movflags", "+faststart",
        "-f", "mp4",
        str(out),
    ]


class VisibleRecorder:
    """One ffmpeg process per recording; ``start``/``stop`` are called with the thermal recorder."""

    def __init__(self, *, ffmpeg: str, url: str, popen: PopenFactory = subprocess.Popen) -> None:
        self._ffmpeg = ffmpeg
        self._url = url
        self._popen = popen
        self._lock = threading.Lock()
        self._proc: _Proc | None = None
        self._state = VisibleState.IDLE
        self._error: str | None = None
        self._out: Path | None = None
        self._started_ns: int | None = None
        self._cmd: list[str] = []
        self._stderr: deque[str] = deque(maxlen=STDERR_TAIL_LINES)
        self._stderr_thread: threading.Thread | None = None

    def _pump_stderr(self, stream: Any) -> None:
        try:
            for raw in iter(stream.readline, b""):
                self._stderr.append(raw.decode("utf-8", "replace").rstrip())
        except (OSError, ValueError):
            pass

    @property
    def state(self) -> VisibleState:
        self._check_alive()
        return self._state

    def _check_alive(self) -> None:
        with self._lock:
            p = self._proc
            if p is None or self._state is not VisibleState.RECORDING:
                return
            rc = p.poll()
            if rc is not None:
                self._state = VisibleState.ERROR
                self._error = f"ffmpeg exited with code {rc} while recording"
                logger.error(self._error)

    def start(self, exp_dir: Path) -> dict[str, Any]:
        with self._lock:
            if self._state is VisibleState.RECORDING:
                raise RuntimeError("visible recorder already running")
            out = Path(exp_dir) / FILE_NAME
            self._cmd = ffmpeg_command(self._ffmpeg, self._url, out)
            self._started_ns = time.time_ns()
            self._stderr.clear()
            self._proc = self._popen(
                self._cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            stderr = getattr(self._proc, "stderr", None)
            if stderr is not None:
                self._stderr_thread = threading.Thread(
                    target=self._pump_stderr, args=(stderr,), name="ffmpeg-stderr", daemon=True
                )
                self._stderr_thread.start()
            self._out = out
            self._state = VisibleState.RECORDING
            self._error = None
            logger.info("visible recorder started: %s", redact_url(self._url))
        return self.stats()

    def stop(self, *, timeout_s: float = 15.0) -> dict[str, Any]:
        with self._lock:
            p, out = self._proc, self._out
            if p is None or out is None:
                return self.stats()
            rc = p.poll()
            if rc is None:
                try:
                    p.stdin.write(b"q")
                    p.stdin.flush()
                    p.stdin.close()
                except (OSError, ValueError):
                    pass
                try:
                    rc = p.wait(timeout=timeout_s)
                except subprocess.TimeoutExpired:
                    logger.warning("ffmpeg did not stop within %.0fs; terminating", timeout_s)
                    p.terminate()
                    try:
                        rc = p.wait(timeout=5.0)
                    except subprocess.TimeoutExpired:
                        p.kill()
                        rc = p.wait(timeout=5.0)
            stopped_ns = time.time_ns()
            t = self._stderr_thread
            if t is not None:
                t.join(timeout=2.0)
            size = out.stat().st_size if out.is_file() else 0
            error = self._error if rc not in (0, None) else None
            if rc not in (0, None) and error is None:
                error = f"ffmpeg exited with code {rc}"
            if size == 0:
                error = error or "no video data was written (camera unreachable or stream refused)"
                if out.exists():
                    out.unlink()  # an empty MP4 would look like a recording that never happened
                digest = None
            else:
                digest = hashlib.sha256(out.read_bytes()).hexdigest()
            if error:
                self._error = error
                logger.error("visible recorder: %s", error)
            info = {
                "file": FILE_NAME if size > 0 else None,
                "path": str(out) if size > 0 else None,
                "url": redact_url(self._url),
                "command": [redact_url(a) if a.startswith("rtsp://") else a for a in self._cmd],
                "started_host_ns": self._started_ns,
                "stopped_host_ns": stopped_ns,
                "returncode": rc,
                "size_bytes": size,
                "sha256": digest,
                "sync": SYNC_NOTE,
                "error": error,
                "stderr_tail": list(self._stderr),
            }
            (out.parent / SIDECAR_NAME).write_text(json.dumps(info, indent=2))
            self._proc = None
            self._state = VisibleState.ERROR if error else VisibleState.IDLE
            logger.info("visible recorder stopped: rc=%s size=%d", rc, size)
            return info

    def stats(self) -> dict[str, Any]:
        self._check_alive()
        with self._lock:
            return {
                "state": self._state.value,
                "file": str(self._out) if self._out else None,
                "started_host_ns": self._started_ns,
                "url": redact_url(self._url),
                "error": self._error,
                "stderr_tail": list(self._stderr),
            }


def default_visible_factory(dotenv: Path | None = None) -> Callable[[], VisibleRecorder] | None:
    """Factory for the real recorder; None (logged) when ffmpeg or credentials are missing."""
    ffmpeg = find_ffprobe(FFMPEG_CANDIDATES)
    host, user, password = credentials(dotenv)
    if ffmpeg is None:
        logger.warning("visible recorder unavailable: ffmpeg not found")
        return None
    if not host or not user:
        logger.warning("visible recorder unavailable: FRI_CAMERA_HOST / FRI_RTSP_USER not set")
        return None
    url = build_rtsp_url(host, RTSP_PATHS["visible_full"], user=user, password=password)
    return lambda: VisibleRecorder(ffmpeg=ffmpeg, url=url)


__all__ = [
    "FILE_NAME",
    "SIDECAR_NAME",
    "VisibleRecorder",
    "VisibleState",
    "default_visible_factory",
    "ffmpeg_command",
]
