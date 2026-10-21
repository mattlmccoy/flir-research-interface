"""Builders and fixtures shared by the visible-sample runner tests.

Experiments are built with ``Recorder`` at 640x480 with the real run's ``visible_alignment`` and
``rois`` (tests/fixtures/README.md). Two kinds of clip stand in for ``visible.mp4``:

* synthetic (a white frame, a dark square from 1.0 s on): decode/timing plumbing only, not
  detection truth;
* real crops (the luma crops of the fixture, pasted into a white frame and encoded lossless, so
  the decoded values equal the captured ones): the crop offsets, threshold, area and brightening
  are checked against the values the fixture pins.

The fixtures (``real``, ``clip``, ``short_clip``, ``fixed_threshold``) are bound by name in each
test module that uses them (see the line after the imports there).
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from flir_research_interface.analysis import visible_sample_run as vsr
from flir_research_interface.analysis.visible_sample import (
    ir_to_visible_points,
    pick_rois,
    roi_outline_ir,
)
from flir_research_interface.analysis.visible_sample_run import analyse_visible_sample
from flir_research_interface.camera.base import Frame
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.recording.recorder import Recorder
from flir_research_interface.visible.recorder import FFMPEG_CANDIDATES
from flir_research_interface.visible.rtsp import find_ffprobe

FIXTURES = Path(__file__).parent / "fixtures"
FFMPEG = find_ffprobe(FFMPEG_CANDIDATES)
FFPROBE = find_ffprobe()
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None or FFPROBE is None, reason="ffmpeg not installed")

HOST_T0_NS = 5_000_000_000  # thermal frame 0 arrives at this host time
T_START_S = 25.996  # where the first visible segment starts on the thermal axis (the real run's)
VIS_W, VIS_H = 1280, 960
CSV_COLUMNS = [
    "t_s",
    "segment",
    "frame",
    "keyframe",
    "sample_dark_px",
    "sample_mean_luma",
    "bed_clipped_frac",
    "brightening",
]


@pytest.fixture(scope="module")
def real() -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(
        (FIXTURES / "visible_sample_20261020_144402.json").read_text()
    )
    return doc


def sample_box(real: dict[str, Any]) -> tuple[int, int, int, int]:
    """The mapped sample ROI's bounding box in visible pixels: x0, y0, w, h."""
    sample, _ = pick_rois(real["rois"])
    assert sample is not None
    pts = ir_to_visible_points(roi_outline_ir(sample), real["visible_alignment"]["H"])
    x0, y0 = np.floor(pts.min(axis=0)).astype(int)
    x1, y1 = np.ceil(pts.max(axis=0)).astype(int)
    return int(x0), int(y0), int(x1 - x0), int(y1 - y0)


def synthetic_clip(path: Path, real: dict[str, Any], seconds: float, dark_from_s: float) -> Path:
    """White 1280x960 at 10 fps with a dark square over the sample from ``dark_from_s`` on."""
    assert FFMPEG is not None
    x, y, w, h = sample_box(real)
    subprocess.run(
        [
            FFMPEG, "-v", "error", "-y",
            "-f", "lavfi", "-i", "color=white:s=1280x960:r=10", "-t", str(seconds),
            "-vf", f"drawbox=x={x}:y={y}:w={w}:h={h}:color=black:t=fill:"
                   f"enable='gte(t,{dark_from_s})'",
            "-c:v", "libx264", "-profile:v", "baseline", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-x264-params", "keyint=5", str(path),
        ],
        check=True,
    )  # fmt: skip
    return path


def lossless_clip(path: Path, planes: list[np.ndarray]) -> Path:
    """Encode full-frame luma planes (grey chroma) lossless, 10 fps, so decoding returns them."""
    assert FFMPEG is not None
    grey = bytes([128]) * (VIS_W * VIS_H // 2)
    raw = b"".join(p.tobytes() + grey for p in planes)
    subprocess.run(
        [
            FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "yuv420p",
            "-s", f"{VIS_W}x{VIS_H}", "-r", "10", "-i", "-",
            "-c:v", "libx264", "-qp", "0", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            str(path),
        ],
        input=raw, check=True,
    )  # fmt: skip
    return path


@pytest.fixture(scope="module")
def clip(tmp_path_factory: pytest.TempPathFactory, real: dict[str, Any]) -> Path:
    """synthetic: 3 s, dark square from 1.0 s."""
    return synthetic_clip(tmp_path_factory.mktemp("clip") / "c.mp4", real, 3.0, 1.0)


@pytest.fixture(scope="module")
def short_clip(tmp_path_factory: pytest.TempPathFactory, real: dict[str, Any]) -> Path:
    """synthetic: 1.5 s, dark square from 0.5 s."""
    return synthetic_clip(tmp_path_factory.mktemp("short") / "s.mp4", real, 1.5, 0.5)


@pytest.fixture
def fixed_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """The synthetic scene has two luma levels, where Otsu's tie goes to the lower one and so
    calls the dark square not dark. These tests are about plumbing, so fix the threshold."""
    monkeypatch.setattr(vsr, "otsu_threshold", lambda values: 128)


def experiment(
    root: Path,
    real: dict[str, Any],
    clips: list[Path] | None = None,
    *,
    gap_s: float = 50.0,
    alignment: dict[str, Any] | bool = True,
    rois: list[dict[str, Any]] | None = None,
) -> Path:
    """A 640x480 recording with the real alignment and ROIs and ``clips`` as visible segments.

    Segment i starts ``i * gap_s`` after the first, which starts at T_START_S.
    """
    rec = Recorder(None, experiments_root=root, chunk_frames=4)
    extra: dict[str, Any] = {"rois": real["rois"] if rois is None else rois}
    if alignment is True:
        extra["visible_alignment"] = real["visible_alignment"]
    elif alignment:
        extra["visible_alignment"] = alignment
    d = rec.start(
        name="vis",
        metadata={},
        camera_info={"backend": "simulated", "ir_format": "TemperatureLinear10mK", "model": "Sim"},
        extra=extra,
    )
    for i in range(3):
        rec.submit(
            Frame(
                frame_id=1 + i,
                device_timestamp_ns=1_000_000_000 + i * 100_000_000,
                host_timestamp_ns=HOST_T0_NS + i * 100_000_000,
                pixel_format="Mono16",
                ir_format="TemperatureLinear10mK",
                counts=np.full((480, 640), 29815, dtype=np.uint16),
                incomplete=False,
            )
        )
    rec.stop()
    segments = []
    for i, src in enumerate(clips or []):
        name = "visible.mp4" if i == 0 else f"visible_{i:03d}.mp4"
        shutil.copy(src, d / name)
        started = HOST_T0_NS + round((T_START_S + i * gap_s) * 1e9)
        segments.append(
            {
                "index": i,
                "file": name,
                "started_host_ns": started - 1_000_000_000,
                "first_frame_host_ns": started,
                "duration_s": 3.0,
                "offset_s": i * gap_s,
            }
        )
    if segments:
        side = {"file": "visible.mp4", "started_host_ns": segments[0]["started_host_ns"]}
        (d / "visible.json").write_text(json.dumps({**side, "segments": segments}))
    return d


def run_analysis(d: Path, **kw: Any) -> dict[str, Any]:
    return analyse_visible_sample(ExperimentReader(d), **kw)


def exported(d: Path) -> list[str]:
    folder = d / "exports"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def csv_rows(d: Path) -> list[dict[str, str]]:
    with (d / "exports" / "visible_sample.csv").open(newline="") as fh:
        return list(csv.DictReader(fh))


def packet_times(path: Path) -> list[float]:
    assert FFPROBE is not None
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return [float(x) for x in out.split()]


def video_size(path: Path) -> tuple[int, int]:
    assert FFPROBE is not None
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    w, h = out.strip().split(",")
    return int(w), int(h)
