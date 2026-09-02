"""Live preview of the visible camera: ffmpeg transcodes RTSP ``/avc/ch1`` to an MJPEG stream.

This is a *view* only (spec: the visible camera never displaces the radiometric stream). The
camera throttles its RTSP encoder while GigE streams (docs/visible_camera.md), so a small,
low-rate MJPEG (default 640 px wide, 8 fps) is all that is worth relaying to the browser.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable, Iterator
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


def mjpeg_command(ffmpeg: str, url: str, *, fps: int = 8, width: int = 640) -> list[str]:
    """ffmpeg argv producing multipart MJPEG on stdout from the RTSP stream."""
    return [
        ffmpeg,
        "-hide_banner", "-loglevel", "error", "-nostdin",
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
    """Runs one ffmpeg per viewer and yields its stdout; the process dies with the viewer."""

    content_type = f"multipart/x-mixed-replace; boundary={BOUNDARY}"

    def __init__(self, *, cmd: list[str], popen: Callable[..., Any] = subprocess.Popen) -> None:
        self._cmd = cmd
        self._popen = popen

    def stream(self) -> Iterator[bytes]:
        proc = self._popen(
            self._cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        try:
            while True:
                chunk = proc.stdout.read(CHUNK)
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=3.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=3.0)
                else:
                    proc.terminate()
            except (OSError, ValueError):
                pass


def default_preview_factory(dotenv: Path | None = None) -> Callable[[], MjpegRelay] | None:
    """Factory for the real relay; None when ffmpeg or RTSP credentials are missing."""
    ffmpeg = find_ffprobe(FFMPEG_CANDIDATES)
    host, user, password = credentials(dotenv)
    if ffmpeg is None or not host or not user:
        return None
    url = build_rtsp_url(host, RTSP_PATHS["visible_full"], user=user, password=password)
    return lambda: MjpegRelay(cmd=mjpeg_command(ffmpeg, url))


__all__ = ["BOUNDARY", "MjpegRelay", "default_preview_factory", "mjpeg_command"]
