"""Live preview of the visible camera: ffmpeg transcodes RTSP ``/avc/ch1`` to an MJPEG stream.

This is a *view* only (spec: the visible camera never displaces the radiometric stream). The
camera throttles its RTSP encoder while GigE streams (docs/visible_camera.md), so a small,
low-rate MJPEG (default 640 px wide, 8 fps) is all that is worth relaying to the browser.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import subprocess
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

from flir_research_interface.visible.recorder import FFMPEG_CANDIDATES, SOCKET_TIMEOUT_US
from flir_research_interface.visible.rtsp import (
    RTSP_PATHS,
    build_rtsp_url,
    credentials,
    find_ffprobe,
)

logger = logging.getLogger(__name__)

BOUNDARY = "ffmpeg"  # ffmpeg's mpjpeg muxer uses this boundary string
CHUNK = 64 * 1024
MAX_VIEWERS = 2  # each viewer is one ffmpeg transcode on the operator


def mjpeg_command(ffmpeg: str, url: str, *, fps: int = 8, width: int = 640) -> list[str]:
    """ffmpeg argv producing multipart MJPEG on stdout from the RTSP stream."""
    return [
        ffmpeg,
        "-hide_banner", "-loglevel", "error", "-nostdin",
        # low latency: no stream probing delay, no input/decoder buffering, no reordering
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-probesize", "32",
        "-analyzeduration", "0",
        "-max_delay", "0",
        "-reorder_queue_size", "0",
        "-rtsp_transport", "tcp",
        "-timeout", str(SOCKET_TIMEOUT_US),
        "-i", url,
        "-map", "0:v:0", "-an", "-dn", "-sn",
        "-vf", f"scale={width}:-2",
        "-r", str(fps),
        "-q:v", "6",
        "-f", "mpjpeg",
        "-",
    ]


class MjpegRelay:
    """Runs one ffmpeg per viewer and hands its stdout to the viewer as it arrives.

    A reader thread pulls the raw pipe into a small queue; the consumer (sync or async) drains
    it. If nobody takes a chunk for ``idle_timeout_s`` (the browser aborted the request), the
    reader thread terminates ffmpeg itself, so a transcode can never outlive its viewer.
    """

    content_type = f"multipart/x-mixed-replace; boundary={BOUNDARY}"

    def __init__(
        self,
        *,
        cmd: list[str],
        popen: Callable[..., Any] = subprocess.Popen,
        idle_timeout_s: float = 5.0,
    ) -> None:
        self._cmd = cmd
        self._popen = popen
        self._idle_timeout_s = idle_timeout_s
        self._proc: Any = None
        self._closed = False
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=8)
        self._thread: threading.Thread | None = None

    def _pump(self) -> None:
        out = self._proc.stdout  # raw (unbuffered) pipe: read() returns what is available
        try:
            while not self._closed:
                chunk = out.read(CHUNK)
                if not chunk:
                    break
                try:
                    self._queue.put(chunk, timeout=self._idle_timeout_s)
                except queue.Full:
                    logger.info("visible preview: viewer stopped consuming; stopping ffmpeg")
                    break
        except (OSError, ValueError):
            pass
        finally:
            self.close()
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass

    def _start(self) -> None:
        self._proc = self._popen(
            self._cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,  # unbuffered pipe: every JPEG goes out the moment ffmpeg writes it
        )
        self._thread = threading.Thread(target=self._pump, name="mjpeg-relay", daemon=True)
        self._thread.start()

    def close(self) -> None:
        """Stop the transcode (idempotent). Called when the viewer disconnects."""
        self._closed = True
        proc = self._proc
        if proc is None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3.0)
        except (OSError, ValueError):
            pass

    def stream(self) -> Iterator[bytes]:
        """Synchronous consumer (tests, scripts)."""
        self._start()
        try:
            while True:
                chunk = self._queue_get()
                if chunk is None:
                    break
                yield chunk
        finally:
            self.close()

    async def aiter(self) -> AsyncIterator[bytes]:
        """Async consumer for StreamingResponse: cancellation on client disconnect closes ffmpeg."""
        self._start()
        loop = asyncio.get_running_loop()
        try:
            while True:
                chunk = await loop.run_in_executor(None, self._queue_get)
                if chunk is None:
                    break
                yield chunk
        finally:
            self.close()

    def _queue_get(self) -> bytes | None:
        """Next chunk, or None once the pump has finished and the queue is drained."""
        while True:
            try:
                return self._queue.get(timeout=0.5)
            except queue.Empty:
                if self._closed:
                    return None


def default_preview_factory(dotenv: Path | None = None) -> Callable[[], MjpegRelay] | None:
    """Factory for the real relay; None when ffmpeg or RTSP credentials are missing."""
    ffmpeg = find_ffprobe(FFMPEG_CANDIDATES)
    host, user, password = credentials(dotenv)
    if ffmpeg is None or not host or not user:
        return None
    url = build_rtsp_url(host, RTSP_PATHS["visible_full"], user=user, password=password)
    return lambda: MjpegRelay(cmd=mjpeg_command(ffmpeg, url))


__all__ = ["BOUNDARY", "MjpegRelay", "default_preview_factory", "mjpeg_command"]
