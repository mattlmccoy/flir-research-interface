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
RECONNECT_BACKOFF_S = (1.0, 2.0, 5.0, 10.0)
"""Delays between reconnect attempts after a mid-recording stream loss; the last one repeats."""
WATCH_INTERVAL_S = 0.5


def segment_file(index: int) -> str:
    """``visible.mp4`` for the first segment, ``visible_001.mp4`` … after each stream loss."""
    return FILE_NAME if index == 0 else f"visible_{index:03d}.mp4"


class VisibleRecorder:
    """One ffmpeg process per segment; ``start``/``stop`` are called with the thermal recorder.

    A stream loss mid-recording (ffmpeg exits after writing video — on a socket timeout it exits
    0) closes the current segment and reconnects with backoff into ``visible_NNN.mp4`` for as
    long as the recording runs. Segments and the gaps between them go to ``visible.json``.
    """

    def __init__(
        self,
        *,
        ffmpeg: str,
        url: str,
        popen: PopenFactory = subprocess.Popen,
        probe: Probe | None = ffprobe_facts,
        restart_delay_s: float = RESTART_DELAY_S,
        backoff_s: tuple[float, ...] = RECONNECT_BACKOFF_S,
        clock: Callable[[], float] = time.monotonic,
        watch_interval_s: float | None = WATCH_INTERVAL_S,
    ) -> None:
        self._restart_delay_s = restart_delay_s
        self._backoff_s = backoff_s
        self._clock = clock
        self._watch_interval_s = watch_interval_s
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
        self._exp_dir: Path | None = None
        self._out: Path | None = None
        self._started_ns: int | None = None
        self._seg_index = 0
        self._seg_started_ns = 0
        self._segments: list[dict[str, Any]] = []
        self._relaunch_at: float | None = None
        self._backoff_step = 0
        self._cmd: list[str] = []
        self._stderr: deque[str] = deque(maxlen=STDERR_TAIL_LINES)
        self._stderr_thread: threading.Thread | None = None
        self._watch_stop = threading.Event()
        self._watch_thread: threading.Thread | None = None
        self._redact = _redactor(url)

    def _pump_stderr(self, stream: Any) -> None:
        try:
            for raw in iter(stream.readline, b""):
                self._stderr.append(self._redact(raw.decode("utf-8", "replace").rstrip()))
        except (OSError, ValueError):
            pass

    def _watch(self) -> None:
        """Keeps reconnecting while nobody polls ``stats`` (e.g. no browser open)."""
        assert self._watch_interval_s is not None
        while not self._watch_stop.wait(self._watch_interval_s):
            self._check_alive()
            if self._state is not VisibleState.RECORDING:
                return

    @property
    def state(self) -> VisibleState:
        self._check_alive()
        return self._state

    def _check_alive(self) -> None:
        with self._lock:
            if self._proc is None or self._state is not VisibleState.RECORDING:
                return
            if self._relaunch_at is not None:
                if self._clock() >= self._relaunch_at:
                    self._relaunch_at = None
                    logger.info("visible recorder reconnecting into %s", self._out_name())
                    self._launch()
                return
            rc = self._proc.poll()
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
            if self._current_has_data():
                self._close_segment(rc)
                self._seg_index += 1
                self._backoff_step = 0
                self._schedule_relaunch()
                logger.warning(
                    "ffmpeg exited with code %s mid-recording (stream lost); reconnecting into %s",
                    rc,
                    self._out_name(),
                )
                return
            if self._segments:  # a reconnect attempt that got nothing: keep trying
                self._discard_empty()
                self._backoff_step += 1
                self._schedule_relaunch()
                return
            self._state = VisibleState.ERROR
            suffix = f" (after {self._restarts} retries)" if self._restarts else ""
            self._error = f"ffmpeg exited with code {rc} while recording{suffix}"
            logger.error(self._error)

    def _can_relaunch(self, rc: int) -> bool:
        """Only a start-up failure is retried: nonzero exit, nothing written, early in the run."""
        if rc == 0 or self._restarts >= MAX_RESTARTS or self._out is None or self._segments:
            return False
        if self._clock() - self._launch_mono > RESTART_WINDOW_S:
            return False
        return not self._current_has_data()

    def _current_has_data(self) -> bool:
        return self._out is not None and self._out.is_file() and self._out.stat().st_size > 0

    def _discard_empty(self) -> None:
        if self._out is not None and self._out.exists():
            self._out.unlink()  # an empty MP4 would look like a recording that never happened

    def _out_name(self) -> str:
        return segment_file(self._seg_index)

    def _schedule_relaunch(self) -> None:
        delay = self._backoff_s[min(self._backoff_step, len(self._backoff_s) - 1)]
        self._relaunch_at = self._clock() + delay

    def _close_segment(self, rc: int | None) -> None:
        self._segments.append(
            {
                "index": self._seg_index,
                "file": self._out_name(),
                "started_host_ns": self._seg_started_ns,
                "stopped_host_ns": time.time_ns(),
                "returncode": rc,
            }
        )

    def _launch(self) -> None:
        """Start ffmpeg for the current segment (lock held by caller)."""
        assert self._exp_dir is not None
        self._out = self._exp_dir / self._out_name()
        self._cmd = ffmpeg_command(self._ffmpeg, self._url, self._out)
        self._launch_mono = self._clock()
        self._seg_started_ns = time.time_ns()
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
            self._exp_dir = Path(exp_dir)
            self._started_ns = time.time_ns()
            self._stderr.clear()
            self._restarts = 0
            self._seg_index = 0
            self._segments = []
            self._relaunch_at = None
            self._backoff_step = 0
            self._launch()
            self._state = VisibleState.RECORDING
            self._error = None
            logger.info("visible recorder started: %s", redact_url(self._url))
            if self._watch_interval_s:
                self._watch_stop.clear()
                self._watch_thread = threading.Thread(
                    target=self._watch, name="visible-watchdog", daemon=True
                )
                self._watch_thread.start()
        return self.stats()

    def _stop_proc(self, p: _Proc, timeout_s: float) -> int | None:
        rc = p.poll()
        if rc is not None:
            return rc
        try:
            p.stdin.write(b"q")
            p.stdin.flush()
            p.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            return p.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            logger.warning("ffmpeg did not stop within %.0fs; terminating", timeout_s)
            p.terminate()
            try:
                return p.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                p.kill()
                return p.wait(timeout=5.0)

    def _segment_facts(self, seg: dict[str, Any], t0_ns: int) -> dict[str, Any]:
        """Size, hash and probed stream facts of one closed segment."""
        assert self._exp_dir is not None
        path = self._exp_dir / seg["file"]
        facts: dict[str, Any] = {
            "frames": None,
            "duration_s": None,
            "width": None,
            "height": None,
            "codec": None,
        }
        if self._probe is not None:
            try:
                facts.update(self._probe(path))
            except Exception as exc:  # noqa: BLE001 - facts are a bonus, never fatal
                logger.warning("visible probe failed: %s", exc)
        fps = (
            facts["frames"] / facts["duration_s"]
            if facts.get("frames") and facts.get("duration_s")
            else None
        )
        return {
            **seg,
            **facts,
            "measured_fps": fps,
            "offset_s": (seg["started_host_ns"] - t0_ns) / 1e9,
            "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    def stop(self, *, timeout_s: float = 15.0) -> dict[str, Any]:
        self._watch_stop.set()
        w = self._watch_thread
        if w is not None and w is not threading.current_thread():
            w.join(timeout=5.0)
        with self._lock:
            p, out = self._proc, self._out
            if p is None or out is None:
                return self.stats()
            reconnecting = self._relaunch_at is not None
            self._relaunch_at = None
            if reconnecting:
                rc = self._segments[-1]["returncode"]
            else:
                rc = self._stop_proc(p, timeout_s)
            stopped_ns = time.time_ns()
            t = self._stderr_thread
            if t is not None:
                t.join(timeout=2.0)
            if not reconnecting:
                if self._current_has_data():
                    self._close_segment(rc)
                    self._segments[-1]["stopped_host_ns"] = stopped_ns
                else:
                    self._discard_empty()
            error = None
            if rc not in (0, None) and not reconnecting:  # a reconnect in progress is not a failure
                error = self._error or f"ffmpeg exited with code {rc}"
            if not self._segments:
                error = error or "no video data was written (camera unreachable or stream refused)"
            t0_ns = self._segments[0]["started_host_ns"] if self._segments else 0
            segments = [self._segment_facts(s, t0_ns) for s in self._segments]
            gaps = self._gaps(stopped_ns if reconnecting else None, t0_ns)
            if error:
                self._error = error
                logger.error("visible recorder: %s", error)
            if gaps:
                logger.warning(
                    "visible recorder: %d stream gap(s), %d segment(s)", len(gaps), len(segments)
                )
            first = segments[0] if segments else None
            facts = {
                k: (first[k] if first else None)
                for k in ("frames", "duration_s", "width", "height", "codec", "measured_fps")
            }
            info = {
                **facts,
                "file": FILE_NAME if first else None,
                "path": str(out.parent / FILE_NAME) if first else None,
                "url": redact_url(self._url),
                "command": [redact_url(a) if a.startswith("rtsp://") else a for a in self._cmd],
                "started_host_ns": self._started_ns,
                "stopped_host_ns": stopped_ns,
                "returncode": rc,
                "restarts": self._restarts,
                "size_bytes": first["size_bytes"] if first else 0,
                "sha256": first["sha256"] if first else None,
                "segments": segments,
                "gaps": gaps,
                "total_size_bytes": sum(s["size_bytes"] for s in segments),
                "sync": SYNC_NOTE,
                "error": error,
                "stderr_tail": list(self._stderr),
            }
            (out.parent / SIDECAR_NAME).write_text(json.dumps(info, indent=2))
            self._proc = None
            self._state = VisibleState.ERROR if error else VisibleState.IDLE
            logger.info(
                "visible recorder stopped: rc=%s size=%d segments=%d",
                rc,
                info["total_size_bytes"],
                len(segments),
            )
            return info

    def _gaps(self, open_until_ns: int | None, t0_ns: int) -> list[dict[str, Any]]:
        """Host-clock holes between segments; an unrecovered loss runs to ``open_until_ns``."""
        segs = self._segments
        bounds = [
            (i, segs[i]["stopped_host_ns"], segs[i + 1]["started_host_ns"])
            for i in range(len(segs) - 1)
        ]
        if open_until_ns is not None and segs:
            bounds.append((len(segs) - 1, segs[-1]["stopped_host_ns"], open_until_ns))
        return [
            {
                "after_segment": i,
                "start_host_ns": a,
                "end_host_ns": b,
                "start_s": (a - t0_ns) / 1e9,
                "duration_s": max(0, b - a) / 1e9,
            }
            for i, a, b in bounds
        ]

    def stats(self) -> dict[str, Any]:
        self._check_alive()
        with self._lock:
            reconnecting = self._relaunch_at is not None
            return {
                "state": self._state.value,
                "file": str(self._out) if self._out else None,
                "started_host_ns": self._started_ns,
                "url": redact_url(self._url),
                "error": self._error,
                "restarts": self._restarts,
                "reconnecting": reconnecting,
                "segments": len(self._segments) + (0 if reconnecting else 1),
                "gaps": len(self._segments) if self._proc is not None else 0,
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
    "segment_file",
]
