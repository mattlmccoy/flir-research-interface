"""Full-range copies of the recorded visible video, for display.

The A70's visible stream is full-range luma (Y 0-255) but the recorded MP4 carries no colour-range
tag, so browsers and ffmpeg read it as TV range and clip everything at or above 235 to white. A
lossless remux with ``video_full_range_flag=1`` tags it ``color_range=pc``; the copy lives under the
run's ``exports/`` and the recording itself is never modified.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from pathlib import Path

from flir_research_interface.visible.recorder import FFMPEG_CANDIDATES
from flir_research_interface.visible.rtsp import find_ffprobe

logger = logging.getLogger(__name__)

FULL = "full"
RAW_UNTAGGED = "raw-untagged"
FULL_RANGE_BSF = "h264_metadata=video_full_range_flag=1"  # tags an H.264 stream color_range=pc
BUILD_TIMEOUT_S = 600

_locks: dict[Path, threading.Lock] = {}
_locks_guard = threading.Lock()
_ffmpeg_found: str | None = None


def resolve_ffmpeg() -> str | None:
    """The ffmpeg the app uses (a working one from ``FFMPEG_CANDIDATES``); None when there is none.

    Only a hit is remembered, so installing ffmpeg while the server runs is picked up.
    """
    global _ffmpeg_found
    if _ffmpeg_found is None:
        _ffmpeg_found = find_ffprobe(FFMPEG_CANDIDATES)
    return _ffmpeg_found


def copy_path(run_dir: Path, file: str) -> Path:
    """``exports/<stem>_full_range.mp4``: ``visible.mp4`` -> ``visible_full_range.mp4``."""
    return run_dir / "exports" / f"{Path(file).stem}_full_range.mp4"


def _is_current(copy: Path, source: Path) -> bool:
    """True when ``copy`` exists and is not older than ``source``."""
    try:
        return copy.stat().st_mtime_ns >= source.stat().st_mtime_ns
    except OSError:
        return False


def _lock_for(path: Path) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(path, threading.Lock())


def _remux(ffmpeg: str, source: Path, part: Path) -> None:
    """Stream-copy ``source`` to ``part`` with the full-range flag set; raises on failure."""
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", str(source), "-map", "0:v:0", "-an", "-dn", "-sn",
        "-c", "copy", "-bsf:v", FULL_RANGE_BSF,
        "-movflags", "+faststart", "-f", "mp4", str(part),
    ]  # fmt: skip
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=BUILD_TIMEOUT_S, check=False)
    if r.returncode != 0:
        raise subprocess.SubprocessError(f"ffmpeg exited {r.returncode}: {r.stderr.strip()[-300:]}")


def full_range_copy(run_dir: Path, file: str, ffmpeg: str | None) -> Path | None:
    """The full-range-tagged copy of ``run_dir/file``, built on first use; None if unavailable.

    The copy is rebuilt when missing or older than the source. It is written to a ``.part`` file and
    moved into place, under a per-file lock, so concurrent requests never see a half-written copy.
    None means "serve the raw file": ffmpeg is missing or the build failed (logged).
    """
    source = run_dir / file
    copy = copy_path(run_dir, file)
    if not source.is_file():
        return None
    if _is_current(copy, source):
        return copy
    if not ffmpeg:
        return None
    with _lock_for(copy):
        if _is_current(copy, source):  # another request built it while this one waited
            return copy
        part = copy.with_name(copy.name + ".part")
        try:
            copy.parent.mkdir(parents=True, exist_ok=True)
            _remux(ffmpeg, source, part)
            os.replace(part, copy)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("full-range copy of %s failed: %s", source, exc)
            part.unlink(missing_ok=True)
            return None
    return copy


def served_range(run_dir: Path, file: str, ffmpeg: str | None) -> str:
    """What a request for ``file`` would serve, without building: ``full`` or ``raw-untagged``.

    ``full`` when an up-to-date copy exists or ffmpeg is available to build it on first request.
    """
    if _is_current(copy_path(run_dir, file), run_dir / file) or ffmpeg:
        return FULL
    return RAW_UNTAGGED


def visible_range(run_dir: Path, ffmpeg: str | None) -> str | None:
    """``full`` / ``raw-untagged`` for the run's visible video; None when it has none."""
    for file in ("visible.mp4", "visible_001.mp4"):
        if (run_dir / file).is_file():
            return served_range(run_dir, file, ffmpeg)
    return None


__all__ = [
    "FULL", "FULL_RANGE_BSF", "RAW_UNTAGGED", "copy_path", "full_range_copy", "resolve_ffmpeg",
    "served_range", "visible_range",
]
