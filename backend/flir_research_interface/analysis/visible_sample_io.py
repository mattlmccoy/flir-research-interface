"""Reading the visible video for the sample analysis: ffprobe for the packets, ffmpeg for the luma;
and the names of the files the analysis writes.

The runner (:mod:`.visible_sample_run`) plans and measures on what these return; nothing here knows
about ROIs or thresholds. :func:`family` names the two result families: the raw analysis
(``visible_sample*``) and the one on the operator's adjusted video (``visible_sample_adjusted*``).
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_S = 300  # ffprobe reads every packet header of a file; a long run takes seconds
DECODE_STALL_S = 120.0  # the decode's ffmpeg is killed when it delivers nothing for this long


RAW_STEM = "visible_sample"
ADJUSTED_STEM = "visible_sample_adjusted"


@dataclass(frozen=True)
class Family:
    """The files of one analysis result, all named from ``stem``: ``<stem>.json``, ``.csv``,
    ``<stem>_plot.png`` and one ``<stem>_closeup[_NNN].mp4`` per segment, each written first as
    ``<name>.part``. Each family's clean-up removes only what :meth:`owns` says is its own, so the
    raw and the adjusted result never delete each other's files."""

    stem: str

    @property
    def json(self) -> str:
        return f"{self.stem}.json"

    @property
    def csv(self) -> str:
        return f"{self.stem}.csv"

    @property
    def plot(self) -> str:
        return f"{self.stem}_plot.png"

    def closeup(self, segment_index: int) -> str:
        """``<stem>_closeup.mp4`` for segment 0, then ``_001``... (like visible_001.mp4)."""
        suffix = "" if segment_index == 0 else f"_{segment_index:03d}"
        return f"{self.stem}_closeup{suffix}.mp4"

    def owns(self, name: str) -> bool:
        """Whether ``name`` in ``exports/`` is one of this family's files (``.part`` included)."""
        base = name.removesuffix(".part")
        if base in (self.json, self.csv, self.plot):
            return True
        return re.fullmatch(rf"{re.escape(self.stem)}_closeup(_\d+)?\.mp4", base) is not None


def family(adjust: Mapping[str, Any] | None) -> Family:
    """The raw family without an adjustment, the adjusted one with any (even a neutral one)."""
    return Family(RAW_STEM if adjust is None else ADJUSTED_STEM)


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


class _StallWatchdog:
    """Kills ``proc`` when the caller has waited more than ``stall_s`` for its output.

    A thread checks while ``waiting(True)`` is in force, so time the caller spends on a frame it
    already has does not count. ``fired`` says that it killed the process. ``stop`` ends the thread.
    """

    def __init__(self, proc: subprocess.Popen[bytes], stall_s: float) -> None:
        self.fired = False
        self._proc, self._stall_s = proc, stall_s
        self._since: float | None = None
        self._done = threading.Event()
        self._thread = threading.Thread(
            target=self._watch, name="visible-decode-watchdog", daemon=True
        )
        self._thread.start()

    def waiting(self, on: bool) -> None:
        self._since = time.monotonic() if on else None

    def stop(self) -> None:
        self._done.set()
        self._thread.join()

    def _watch(self) -> None:
        while not self._done.wait(max(0.01, min(1.0, self._stall_s / 4))):
            since = self._since
            if since is not None and time.monotonic() - since > self._stall_s:
                self.fired = True
                logger.error("ffmpeg decode stalled for %g s; killing it", self._stall_s)
                self._proc.kill()
                return


def decode_luma(
    ffmpeg: str, path: Path, crop: tuple[int, int, int, int]
) -> Iterator[np.ndarray]:
    """Yield the luma crop ``(x, y, w, h)`` of every frame of ``path`` as a ``(h, w)`` uint8 array.

    ``-fps_mode passthrough`` gives exactly one frame per packet (the default inserts duplicates,
    which would shift every later time). Closing the generator early stops ffmpeg. ffmpeg is also
    killed, and ``TimeoutError`` raised, when it gives no output for ``DECODE_STALL_S``.
    """
    x, y, w, h = crop
    cmd = [ffmpeg, "-v", "fatal", "-nostdin", "-i", str(path)]
    cmd += ["-vf", f"extractplanes=y,crop={w}:{h}:{x}:{y}", "-fps_mode", "passthrough"]
    cmd += ["-f", "rawvideo", "-"]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    assert proc.stdout is not None and proc.stderr is not None
    watchdog = _StallWatchdog(proc, DECODE_STALL_S)
    try:
        while True:
            watchdog.waiting(True)
            buf = proc.stdout.read(w * h)
            watchdog.waiting(False)
            if len(buf) != w * h:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(h, w)
        if proc.wait() != 0:
            if watchdog.fired:
                raise TimeoutError(
                    f"ffmpeg decode timed out: no output for {DECODE_STALL_S:g} s on {path.name}"
                )
            tail = proc.stderr.read().decode(errors="replace")[-300:]
            raise RuntimeError(f"ffmpeg decode failed (rc {proc.returncode}): {tail}")
    finally:
        watchdog.stop()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()
        proc.stderr.close()
