"""Media export with the RF-banding filter: the video shows the cleaned frames, says so on the
image and in the file name; ROI values and stats stay raw. Real banded frames from the fixture."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from flir_research_interface.camera.base import Frame
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.recording.recorder import Recorder
from flir_research_interface.visible.recorder import FFMPEG_CANDIDATES
from flir_research_interface.visible.rtsp import find_ffprobe

FX = np.load(Path(__file__).parent / "fixtures" / "rf_banding_frames.npz")
_HAVE_FFMPEG = find_ffprobe(FFMPEG_CANDIDATES) is not None


def _banded(root: Path) -> ExperimentReader:
    rec = Recorder(None, experiments_root=root, chunk_frames=4, min_free_gb=0.0)
    d = rec.start(name="banded", metadata={}, camera_info={"ir_format": "TemperatureLinear10mK"})
    for i in range(3):
        rec.submit(
            Frame(
                frame_id=i + 1,
                device_timestamp_ns=i * 33_333_333,
                host_timestamp_ns=i,
                pixel_format="Mono16",
                ir_format="TemperatureLinear10mK",
                counts=FX["pre_riser_rf_on"],
                incomplete=False,
            )
        )
    rec.stop()
    return ExperimentReader(d)


def _fine_detail(png: bytes) -> float:
    """High-pass energy of the grey image: the ~2.4 px stripes dominate it when present."""
    g = np.asarray(Image.open(BytesIO(png)).convert("L"), dtype=np.float64)[40:-80, 40:-80]
    return float(np.abs(np.diff(g, axis=0)).mean() + np.abs(np.diff(g, axis=1)).mean())


def test_preview_with_the_filter_shows_the_banding_removed(tmp_path: Path) -> None:
    from flir_research_interface.analysis.media import MediaOptions, compose_preview

    r = _banded(tmp_path)
    raw = compose_preview(r, MediaOptions(scale=1, colorbar=False, timestamp=False), 1)
    cleaned = compose_preview(
        r, MediaOptions(scale=1, colorbar=False, timestamp=False, rf_notch=True), 1
    )
    assert _fine_detail(cleaned) < 0.6 * _fine_detail(raw)


@pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg not installed")
def test_filtered_clips_are_named_as_filtered(tmp_path: Path) -> None:
    from flir_research_interface.analysis.media import MediaOptions, render_clip

    r = _banded(tmp_path)
    plain = Path(render_clip(r, MediaOptions(start=0, stop=3, title="banded"))["path"])
    filtered = Path(
        render_clip(r, MediaOptions(start=0, stop=3, title="banded", rf_notch=True))["path"]
    )
    assert not plain.stem.endswith("_rf-filtered")
    assert filtered.stem.endswith("_rf-filtered") and filtered.is_file()


def test_media_api_passes_the_filter_flag(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from flir_research_interface.api.app import create_app

    r = _banded(tmp_path)
    c = TestClient(
        create_app(default_backend="simulated", experiments_root=tmp_path, min_free_gb=0.0)
    )
    q = "index=1&scale=1&colorbar=false&timestamp=false"
    raw = c.get(f"/api/experiments/{r.path.name}/export/media/preview?{q}").content
    cleaned = c.get(
        f"/api/experiments/{r.path.name}/export/media/preview?{q}&rf_notch=true"
    ).content
    assert _fine_detail(cleaned) < 0.6 * _fine_detail(raw)
