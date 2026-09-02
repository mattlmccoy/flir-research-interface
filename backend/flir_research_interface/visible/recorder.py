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
import re
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


_URL_CREDS = re.compile(r"(rtsp://[^:@/\s]+:)[^@\s]+@")


def _redactor(url: str) -> Callable[[str], str]:
    """Scrubs the password (and any rtsp://user:pass@ pattern) from ffmpeg's chatter."""
    m = _URL_CREDS.search(url)
    password = m.group(0)[len(m.group(1)) : -1] if m else None

    def redact(line: str) -> str:
        line = _URL_CREDS.sub(r"\1***@", line)
        if password:
            line = line.replace(password, "***")
        return line

    return redact


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
Probe = Callable[[Path], dict[str, Any]]


def ffprobe_facts(path: Path, *, ffprobe: str | None = None) -> dict[str, Any]:
    """Frame count, duration, size and codec of a finished MP4 (counting frames, not headers)."""
    exe = ffprobe or find_ffprobe()
    if exe is None:
        raise RuntimeError("ffprobe not found")
    out = subprocess.run(
        [
            exe,
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,nb_read_frames:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    j = json.loads(out.stdout)
    st = (j.get("streams") or [{}])[0]
    return {
        "frames": int(st.get("nb_read_frames") or 0),
        "duration_s": float((j.get("format") or {}).get("duration") or 0.0),
        "width": st.get("width"),
        "height": st.get("height"),
        "codec": st.get("codec_name"),
    }


def ffmpeg_command(ffmpeg: str, url: str, out: Path) -> list[str]:
    """ffmpeg argv: TCP transport, wall-clock packet timestamps, video-only stream copy to MP4."""
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",  # stdin stays open on purpose: 'q' is the graceful stop that finalises the MP4
        "-rtsp_transport",
        "tcp",
        "-timeout",
        str(SOCKET_TIMEOUT_US),
        "-use_wallclock_as_timestamps",
        "1",
        "-i",
        url,
        "-map",
        "0:v:0",
        "-an",
        "-dn",
        "-sn",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        str(out),
    ]


MAX_RESTARTS = 3
"""Relaunch ffmpeg this many times when it dies before writing anything (RTSP open refused)."""
RESTART_WINDOW_S = 15.0
"""Only relaunch within this many seconds of the start: a later death is a real stream loss."""
RESTART_DELAY_S = 1.0


class VisibleRecorder:
    """One ffmpeg process per recording; ``start``/``stop`` are called with the thermal recorder."""

    def __init__(
        self,
        *,
        ffmpeg: str,
        url: str,
        popen: PopenFactory = subprocess.Popen,
        probe: Probe | None = ffprobe_facts,
        restart_delay_s: float = RESTART_DELAY_S,
    ) -> None:
        self._restart_delay_s = restart_delay_s
        self._restarts = 0
        self._launch_mono = 0.0
        self._ffmpeg = ffmpeg
        self._url = url
        self._popen = popen
        self._probe = probe
        self._lock = threading.Lock()
        self._proc: _Proc | None = None
        self._state = VisibleState.IDLE
        self._error: str | None = None
        self._out: Path | None = None
        self._started_ns: int | None = None
        self._cmd: list[str] = []
        self._stderr: deque[str] = deque(maxlen=STDERR_TAIL_LINES)
        self._stderr_thread: threading.Thread | None = None
        self._redact = _redactor(url)

    def _pump_stderr(self, stream: Any) -> None:
        try:
            for raw in iter(stream.readline, b""):
                self._stderr.append(self._redact(raw.decode("utf-8", "replace").rstrip()))
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
            if rc is None:
                return
            if self._can_relaunch(rc):
                self._restarts += 1
                logger.warning(
                    "ffmpeg exited with code %s before writing anything; relaunching (%d/%d)",
                    rc,
                    self._restarts,
                    MAX_RESTARTS,
                )
                time.sleep(self._restart_delay_s)
                self._launch()
                return
            self._state = VisibleState.ERROR
            suffix = f" (after {self._restarts} retries)" if self._restarts else ""
            self._error = f"ffmpeg exited with code {rc} while recording{suffix}"
            logger.error(self._error)

    def _can_relaunch(self, rc: int) -> bool:
        """Only a start-up failure is retried: nonzero exit, nothing written, early in the run."""
        if rc == 0 or self._restarts >= MAX_RESTARTS or self._out is None:
            return False
        if time.monotonic() - self._launch_mono > RESTART_WINDOW_S:
            return False
        return not self._out.is_file() or self._out.stat().st_size == 0

    def _launch(self) -> None:
        """Start ffmpeg (lock held by caller)."""
        self._launch_mono = time.monotonic()
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

    def start(self, exp_dir: Path) -> dict[str, Any]:
        with self._lock:
            if self._state is VisibleState.RECORDING:
                raise RuntimeError("visible recorder already running")
            out = Path(exp_dir) / FILE_NAME
            self._cmd = ffmpeg_command(self._ffmpeg, self._url, out)
            self._started_ns = time.time_ns()
            self._stderr.clear()
            self._restarts = 0
            self._out = out
            self._launch()
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
            facts: dict[str, Any] = {
                "frames": None,
                "duration_s": None,
                "width": None,
                "height": None,
                "codec": None,
            }
            if size > 0 and self._probe is not None:
                try:
                    facts.update(self._probe(out))
                except Exception as exc:  # noqa: BLE001 - facts are a bonus, never fatal
                    logger.warning("visible probe failed: %s", exc)
            fps = (
                facts["frames"] / facts["duration_s"]
                if facts.get("frames") and facts.get("duration_s")
                else None
            )
            info = {
                **facts,
                "measured_fps": fps,
                "file": FILE_NAME if size > 0 else None,
                "path": str(out) if size > 0 else None,
                "url": redact_url(self._url),
                "command": [redact_url(a) if a.startswith("rtsp://") else a for a in self._cmd],
                "started_host_ns": self._started_ns,
                "stopped_host_ns": stopped_ns,
                "returncode": rc,
                "restarts": self._restarts,
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
                "restarts": self._restarts,
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
