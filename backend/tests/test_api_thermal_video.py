"""Thermal preview video: rendered after every stop, served and regenerable per experiment."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.visible.recorder import FFMPEG_CANDIDATES
from flir_research_interface.visible.rtsp import find_ffprobe

pytestmark = pytest.mark.skipif(
    find_ffprobe(FFMPEG_CANDIDATES) is None, reason="ffmpeg not installed"
)


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            default_backend="simulated", sim_fps=60.0, experiments_root=tmp_path, min_free_gb=0.0
        )
    )


def _wait_for(path: Path, timeout: float = 20.0) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if path.is_file():
            return True
        time.sleep(0.1)
    return False


def test_stop_renders_thermal_preview_in_the_background_and_it_is_served(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        d = Path(c.post("/api/recording/start", json={"name": "tv"}).json()["experiment_dir"])
        time.sleep(0.3)
        t0 = time.monotonic()
        assert c.post("/api/recording/stop").status_code == 200
        assert time.monotonic() - t0 < 5.0  # the render must not hold the stop
        out = d / "exports" / "thermal_preview.mp4"
        assert _wait_for(out), "thermal_preview.mp4 was not rendered after stop"
        # the reader/experiment info exposes it once present
        deadline = time.monotonic() + 10
        info = c.get(f"/api/experiments/{d.name}").json()
        while not info.get("thermal_preview") and time.monotonic() < deadline:
            time.sleep(0.1)
            info = c.get(f"/api/experiments/{d.name}").json()
        assert info["thermal_preview"]["bytes"] > 0
        r = c.get(f"/api/experiments/{d.name}/thermal_preview.mp4")
        assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
        assert r.headers.get("accept-ranges") == "bytes" and len(r.content) == out.stat().st_size
        c.post("/api/camera/disconnect")


def test_thermal_video_can_be_regenerated_on_demand(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        d = Path(c.post("/api/recording/start", json={"name": "tv2"}).json()["experiment_dir"])
        time.sleep(0.2)
        c.post("/api/recording/stop")
        c.post("/api/camera/disconnect")
        out = d / "exports" / "thermal_preview.mp4"
        _wait_for(out)
        out.unlink()  # user deleted it: regenerate
        r = c.post(f"/api/experiments/{d.name}/export/thermal-video")
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["path"] == str(out) and j["frames"] > 0 and out.is_file()
        assert c.get("/api/experiments/nope/thermal_preview.mp4").status_code == 404
        assert c.post("/api/experiments/nope/export/thermal-video").status_code == 404
