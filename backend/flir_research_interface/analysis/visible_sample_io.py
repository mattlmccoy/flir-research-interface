"""Reading the visible video for the sample analysis: ffprobe for the packets, ffmpeg for the luma.

The runner (:mod:`.visible_sample_run`) plans and measures on what these return; nothing here knows
about ROIs, thresholds or the files that are written.
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_S = 300  # ffprobe reads every packet header of a file; a long run takes seconds


class NoPacketsError(ValueError):
    """A video file that ffprobe reads without error but that holds no video packet."""


@dataclass(frozen=True)
class Packets:
    """What ffprobe says about one video file: frame size and per-packet time and keyframe flag."""

    width: int
    height: int
    pts_s: np.ndarray
    keyframe: np.ndarray


def probe(ffprobe: str, path: Path) -> Packets:
    """Frame size and the display time and keyframe flag of every packet of ``path``.

    The recorder's stream is Baseline H.264 (no B-frames), so packet order is display order; a file
    where times go backwards is refused rather than analysed on a wrong time axis. A file with no
    video packet (the recorder leaves one when the camera never delivered a frame) raises
    ``NoPacketsError``.
    """
    cmd = [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries"]
    cmd += ["packet=pts_time,flags:stream=width,height", "-of", "json", str(path)]
    run = subprocess.run(cmd, capture_output=True, text=True, timeout=PROBE_TIMEOUT_S)
    if run.returncode != 0:
        raise RuntimeError(f"ffprobe failed (rc {run.returncode}): {run.stderr.strip()[-300:]}")
    doc = json.loads(run.stdout)
    packets, streams = doc.get("packets") or [], doc.get("streams") or []
    if not packets or not streams:
        raise NoPacketsError(f"{path.name} has no video packets")
    pts = np.array([float(p["pts_time"]) for p in packets])
    if np.any(np.diff(pts) < 0):
        raise ValueError(f"packet times in {path.name} are not in display order")
    key = np.array(["K" in str(p.get("flags", "")) for p in packets], dtype=bool)
    return Packets(int(streams[0]["width"]), int(streams[0]["height"]), pts, key)


def decode_luma(
    ffmpeg: str, path: Path, crop: tuple[int, int, int, int]
) -> Iterator[np.ndarray]:
    """Yield the luma crop ``(x, y, w, h)`` of every frame of ``path`` as a ``(h, w)`` uint8 array.

    ``-fps_mode passthrough`` gives exactly one frame per packet (the default inserts duplicates,
    which would shift every later time). Closing the generator early stops ffmpeg.
    """
    x, y, w, h = crop
    cmd = [ffmpeg, "-v", "fatal", "-nostdin", "-i", str(path)]
    cmd += ["-vf", f"extractplanes=y,crop={w}:{h}:{x}:{y}", "-fps_mode", "passthrough"]
    cmd += ["-f", "rawvideo", "-"]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    assert proc.stdout is not None and proc.stderr is not None
    try:
        while len(buf := proc.stdout.read(w * h)) == w * h:
            yield np.frombuffer(buf, dtype=np.uint8).reshape(h, w)
        if proc.wait() != 0:
            tail = proc.stderr.read().decode(errors="replace")[-300:]
            raise RuntimeError(f"ffmpeg decode failed (rc {proc.returncode}): {tail}")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()
        proc.stderr.close()
