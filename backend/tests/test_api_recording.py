"""Recording endpoints against the simulated camera."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        default_backend="simulated",
        sim_fps=60.0,
        viz_fps=30.0,
        experiments_root=tmp_path,
        min_free_gb=0.0,
    )
    return TestClient(app)


def test_recording_lifecycle_and_experiment_listing(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        assert (
            c.post("/api/recording/start", json={"name": "x"}).status_code == 409
        )  # not connected
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        r = c.post(
            "/api/recording/start",
            json={"name": "PA12 Run 1", "metadata": {"operator": "mm", "rf_power_w": 300}},
        )
        assert r.status_code == 200, r.text
        assert r.json()["state"] == "recording"
        assert c.post("/api/recording/start", json={"name": "again"}).status_code == 409
        time.sleep(0.6)
        st = c.get("/api/recording/status").json()
        assert st["state"] == "recording" and st["frames_written"] > 0 and st["queue_dropped"] == 0
        r = c.post("/api/recording/stop")
        assert r.status_code == 200
        man = r.json()
        assert man["complete"] is True and man["frames_written"] > 0
        exps = c.get("/api/experiments").json()
        assert (
            len(exps) == 1
            and exps[0]["complete"] is True
            and exps[0]["frames_on_disk"] == man["frames_written"]
        )
        assert exps[0]["metadata"]["experiment"]["rf_power_w"] == 300
        c.post("/api/camera/disconnect")


def test_disconnect_while_recording_finalizes_first(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        c.post("/api/recording/start", json={"name": "abrupt"})
        time.sleep(0.3)
        c.post("/api/camera/disconnect")
        exps = c.get("/api/experiments").json()
        assert len(exps) == 1 and exps[0]["complete"] is True
        idle = c.get("/api/recording/status").json()
        assert idle["state"] == "idle" and idle["free_space_gb"] is not None
