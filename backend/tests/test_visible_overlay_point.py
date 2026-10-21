"""A point-in-time query of the visible overlay (the export preview) gets a frame.

``compose_preview`` asks the visible source for the window ``[t, t]``; a zero-length window must
still cover one frame when ``t`` is inside a segment (after its ``FRAME0_SKIP_S``), while range
queries keep their meaning. The clip in the preview test is synthetic (ffmpeg lavfi flat white over
a uniform thermal frame): plumbing only, it says nothing about real alignment.
"""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from flir_research_interface.analysis.media import MediaOptions, compose_preview
from flir_research_interface.analysis.visible_overlay import segment_windows
from flir_research_interface.camera.base import Frame
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.playback.visible_timing import FRAME0_SKIP_S
from flir_research_interface.recording.recorder import Recorder
from flir_research_interface.visible.recorder import FFMPEG_CANDIDATES
from flir_research_interface.visible.rtsp import find_ffprobe

FFMPEG = find_ffprobe(FFMPEG_CANDIDATES)
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
W, H = 64, 48
TIMELINE = [{"index": 0, "file": "visible.mp4", "t_start_s": 4.0, "duration_s": 10.0}]


def test_point_query_inside_a_segment_is_one_frame_window() -> None:
    [(name, local, dur, g0)] = segment_windows(TIMELINE, 6.5, 6.5)
    assert name == "visible.mp4"
    assert local == pytest.approx(2.5) and g0 == pytest.approx(6.5)
    assert dur == pytest.approx(0.0)  # the source extracts max(1/fps, dur): one frame


def test_point_query_before_the_skip_or_after_the_end_has_no_window() -> None:
    assert segment_windows(TIMELINE, 4.0 + FRAME0_SKIP_S / 2, 4.0 + FRAME0_SKIP_S / 2) == []
    assert segment_windows(TIMELINE, 3.0, 3.0) == []  # before the video starts
    assert segment_windows(TIMELINE, 14.5, 14.5) == []  # after the segment ends


def test_range_queries_are_unchanged() -> None:
    assert segment_windows(TIMELINE, 5.0, 5.0 + 1e-9)[0][2] == pytest.approx(1e-9)
    assert segment_windows(TIMELINE, 6.0, 5.0) == []  # a reversed range stays empty
    assert segment_windows(TIMELINE, 0.0, 4.0 + FRAME0_SKIP_S) == []  # ends where the skip ends


def _run_with_white_video(root: Path, n: int = 30) -> ExperimentReader:
    """synthetic: a uniform thermal run (frames 33 ms apart) with a flat-white 2 s visible clip
    starting with thermal frame 0 and an identity alignment."""
    assert FFMPEG is not None
    rec = Recorder(None, experiments_root=root, chunk_frames=8, min_free_gb=0.0)
    d = rec.start(name="point", metadata={},
                  camera_info={"ir_format": "TemperatureLinear10mK", "model": "Sim"},
                  extra={"visible_alignment": {"H": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}})
    for i in range(n):
        counts = np.full((H, W), 29815, dtype=np.uint16)
        counts[0, 0] = 29815 + 500  # a span, so the colour map is not degenerate
        rec.submit(Frame(frame_id=i, device_timestamp_ns=i * 33_333_333,
                         host_timestamp_ns=i * 33_333_333, pixel_format="Mono16",
                         ir_format="TemperatureLinear10mK", counts=counts, incomplete=False))
    rec.stop()
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", f"color=c=white:size={W}x{H}:rate=10:duration=2", "-pix_fmt", "yuvj420p",
         "-c:v", "libx264", "-g", "5", str(d / "visible.mp4")],
        check=True,
    )  # fmt: skip
    (d / "visible.json").write_text(json.dumps({
        "file": "visible.mp4", "started_host_ns": 0, "duration_s": 2.0, "measured_fps": 6.0,
        "width": W, "height": H,
    }))  # fmt: skip
    return ExperimentReader(d)


def _mean(png: bytes) -> float:
    return float(np.asarray(Image.open(io.BytesIO(png)).convert("L"), dtype=np.float64).mean())


@needs_ffmpeg
def test_preview_shows_the_visible_overlay(tmp_path: Path) -> None:
    """synthetic: plumbing only. At t = 0.5 s (past the skip) the white overlay brightens the
    preview; with the overlay off it does not."""
    reader = _run_with_white_video(tmp_path)
    index = 15
    assert float(reader.t_s(index)) > FRAME0_SKIP_S
    base = dict(scale=1, colorbar=False, timestamp=False)
    off = compose_preview(reader, MediaOptions(visible_opacity=0.0, **base), index)
    on = compose_preview(reader, MediaOptions(visible_opacity=1.0, **base), index)
    assert _mean(on) > _mean(off) + 50
