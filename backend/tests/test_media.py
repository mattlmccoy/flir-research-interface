"""Media export: windowed clip (mp4/gif) with overlays, and the ROI-stats companion."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from flir_research_interface.camera.base import Frame
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.recording.recorder import Recorder
from flir_research_interface.visible.recorder import FFMPEG_CANDIDATES
from flir_research_interface.visible.rtsp import find_ffprobe

_HAVE_FFMPEG = find_ffprobe(FFMPEG_CANDIDATES) is not None
W, H = 64, 48


def _make(root: Path, n: int = 20) -> ExperimentReader:
    rec = Recorder(None, experiments_root=root, chunk_frames=4, min_free_gb=0.0)
    d = rec.start(name="clip", metadata={},
                  camera_info={"ir_format": "TemperatureLinear10mK", "model": "Sim"})
    for i in range(n):
        counts = np.full((H, W), 29815, dtype=np.uint16)
        counts[10:30, 20:44] = 29815 + 400 * (i + 1)
        rec.submit(Frame(frame_id=i, device_timestamp_ns=i * 33_333_333, host_timestamp_ns=i,
                         pixel_format="Mono16", ir_format="TemperatureLinear10mK",
                         counts=counts, incomplete=False))
    rec.stop()
    return ExperimentReader(d)


def test_clip_window_validation(tmp_path: Path) -> None:
    from flir_research_interface.analysis.media import MediaOptions, render_clip
    r = _make(tmp_path)
    with pytest.raises(ValueError):
        render_clip(r, MediaOptions(start=10, stop=5))  # stop <= start
    with pytest.raises(ValueError):
        render_clip(r, MediaOptions(start=0, stop=999))  # beyond n_frames


@pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg not installed")
def test_clip_renders_mp4_for_the_window(tmp_path: Path) -> None:
    from flir_research_interface.analysis.media import MediaOptions, render_clip
    r = _make(tmp_path)
    seen: list[tuple[int, int]] = []
    info = render_clip(r, MediaOptions(start=4, stop=16, fmt="mp4", title="Test clip"),
                       on_progress=lambda d, t: seen.append((d, t)))
    out = Path(info["path"])
    assert out.is_file() and out.suffix == ".mp4" and out.stat().st_size > 0
    assert info["frames"] == 12
    assert seen and seen[-1][0] == seen[-1][1] == 12


@pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg not installed")
def test_clip_renders_gif_with_size_guard(tmp_path: Path) -> None:
    from flir_research_interface.analysis.media import MediaOptions, render_clip
    r = _make(tmp_path)
    info = render_clip(r, MediaOptions(start=0, stop=20, fmt="gif", scale=2))
    out = Path(info["path"])
    assert out.is_file() and out.suffix == ".gif" and out.stat().st_size > 0


@pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg not installed")
def test_media_export_api_job(tmp_path: Path) -> None:
    import time

    from fastapi.testclient import TestClient

    from flir_research_interface.api.app import create_app

    with TestClient(create_app(default_backend="simulated", sim_fps=60.0,
                               experiments_root=tmp_path, min_free_gb=0.0)) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        rec = c.post("/api/recording/start", json={"name": "clip"}).json()
        name = Path(rec["experiment_dir"]).name
        time.sleep(0.3)
        c.post("/api/recording/stop")
        c.post("/api/camera/disconnect")
        r = c.post(f"/api/experiments/{name}/export/media",
                   json={"start": 0, "stop": 8, "fmt": "gif", "title": "My clip",
                         "frame_stats": True})
        assert r.status_code == 200 and r.json()["state"] == "running"
        t0 = time.monotonic()
        while time.monotonic() - t0 < 30:
            job = c.get(f"/api/experiments/{name}/export/media/status").json()
            if job["state"] in ("done", "error"):
                break
            time.sleep(0.1)
        assert job["state"] == "done", job
        fname = job["file"]["name"]
        assert fname.endswith(".gif")
        assert c.get(f"/api/experiments/{name}/exports/clips/{fname}").status_code == 200
