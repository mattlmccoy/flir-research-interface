"""The close-up video keeps every analysed frame at its source time, in display order.

The visible stream is recorded with ``-use_wallclock_as_timestamps 1``, so its frame times are
irregular (about 1 ms to 840 ms apart on the real run). The clip here is synthetic: timing plumbing
only, not detection truth. Its frame spacings cycle through values like the real stream's, so any
encoder step that snaps frames to a coarser grid (and merges the ones that fall on the same tick) or
stores them out of display order shows up as a wrong count or wrong times.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from flir_research_interface.analysis import visible_sample_run as vsr
from flir_research_interface.playback.visible_timing import FRAME0_SKIP_S
from flir_research_interface.visible.recorder import FFMPEG_CANDIDATES
from flir_research_interface.visible.rtsp import find_ffprobe

FFMPEG = find_ffprobe(FFMPEG_CANDIDATES)
FFPROBE = find_ffprobe()
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None or FFPROBE is None, reason="ffmpeg not installed")

GAPS_MS = (33, 42, 79, 98, 136, 310)  # the cycle of spacings between source frames
FRAMES = 60
CROP = (100, 60, 126)  # x, y, side of the close-up crop inside the 320x240 source
STRETCH_LO = 50.0
TOLERANCE_S = 0.001


@dataclass(frozen=True)
class _Timing:
    """What ffprobe says about a video: display-order frame times and packet times/types."""

    frame_pts: np.ndarray
    pict_types: list[str]
    packet_pts: np.ndarray
    packet_dts: np.ndarray


def _entries(path: Path, section: str, fields: str) -> list[dict[str, str]]:
    """ffprobe's ``fields`` of every ``section`` ("frame" or "packet") of the first video stream."""
    assert FFPROBE is not None
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0", "-of", "json"]
        + ["-show_entries", f"{section}={fields}", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    entries: list[dict[str, str]] = json.loads(out)[f"{section}s"]
    return entries


def _timing(path: Path) -> _Timing:
    frames = _entries(path, "frame", "pts_time,pict_type")
    packets = _entries(path, "packet", "pts_time,dts_time")
    return _Timing(
        np.array([float(f["pts_time"]) for f in frames]),
        [str(f["pict_type"]) for f in frames],
        np.array([float(p["pts_time"]) for p in packets]),
        np.array([float(p["dts_time"]) for p in packets]),
    )


def _irregular_clip(path: Path) -> Path:
    """320x240 baseline H.264 (like the recorder's stream), ``FRAMES`` frames starting at 0 s whose
    spacings cycle through ``GAPS_MS``, on a 90 kHz time base (like the real file's)."""
    assert FFMPEG is not None
    n = len(GAPS_MS)
    steps = "+".join(f"gt(mod(N,{n}),{k})*{g / 1000}" for k, g in enumerate(GAPS_MS[:-1]))
    setpts = f"setpts='(floor(N/{n})*{sum(GAPS_MS) / 1000}+{steps})/TB'"
    subprocess.run(
        [
            FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30",
            "-frames:v", str(FRAMES), "-vf", f"settb=1/90000,{setpts}",
            "-c:v", "libx264", "-profile:v", "baseline", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-fps_mode", "passthrough", "-enc_time_base", "1:90000",
            "-video_track_timescale", "90000", str(path),
        ],
        check=True,
    )  # fmt: skip
    return path


@dataclass(frozen=True)
class _Encoded:
    source: _Timing
    closeup: _Timing


@pytest.fixture(scope="module")
def encoded(tmp_path_factory: pytest.TempPathFactory) -> _Encoded:
    """synthetic: timing plumbing only. The source and the close-up the runner makes from it."""
    folder = tmp_path_factory.mktemp("closeup")
    src = _irregular_clip(folder / "src.mp4")
    out = folder / "closeup.mp4"
    assert FFMPEG is not None
    vsr._encode_closeup(FFMPEG, src, out, CROP, STRETCH_LO)
    return _Encoded(_timing(src), _timing(out))


@needs_ffmpeg
def test_synthetic_source_is_irregular(encoded: _Encoded) -> None:
    """synthetic: guards the fixture, a regular clip would pass the other tests for nothing."""
    gaps = np.diff(encoded.source.packet_pts)
    assert len(encoded.source.packet_pts) == FRAMES
    assert gaps.min() < 0.04 and gaps.max() > 0.3
    assert len(set(np.round(gaps, 3))) == len(GAPS_MS)


@needs_ffmpeg
def test_closeup_has_every_frame_after_the_skip(encoded: _Encoded) -> None:
    """synthetic: timing plumbing only."""
    src = encoded.source.packet_pts
    kept = src[src >= src[0] + FRAME0_SKIP_S]
    assert len(kept) < FRAMES  # the skip drops some, so a wrong start would show too
    assert len(encoded.closeup.frame_pts) == len(kept)


@needs_ffmpeg
def test_closeup_frames_keep_their_source_time_in_display_order(encoded: _Encoded) -> None:
    """synthetic: timing plumbing only. The close-up starts at the source's time, not at 0."""
    src = encoded.source.packet_pts
    kept = src[src >= src[0] + FRAME0_SKIP_S]
    pts = encoded.closeup.frame_pts
    assert np.all(np.diff(pts) > 0)
    assert len(pts) == len(kept)
    assert np.abs(pts - kept).max() <= TOLERANCE_S


@needs_ffmpeg
def test_closeup_is_stored_in_display_order_without_b_frames(encoded: _Encoded) -> None:
    """synthetic: timing plumbing only. Packets follow each other in time and need no reordering,
    so a seek to a time lands on the frame labelled with it."""
    closeup = encoded.closeup
    assert np.all(np.diff(closeup.packet_pts) > 0)
    assert np.array_equal(closeup.packet_pts, closeup.packet_dts)
    assert "B" not in closeup.pict_types
