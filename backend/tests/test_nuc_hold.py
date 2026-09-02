"""NUC hold: a NUC right before Record, then NUCMode=Off for the whole recording so the camera
never freezes mid-run (the A70 repeats its image ~2 s during a NUC); restored at stop."""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            default_backend="simulated", sim_fps=60.0, experiments_root=tmp_path, min_free_gb=0.0
        )
    )


def test_recording_holds_nuc_off_and_restores_it(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        assert c.get("/api/camera/info").json()["nuc_mode"] == "Automatic"
        r = c.post("/api/recording/start", json={"name": "hold", "nuc_hold": True})
        assert r.status_code == 200, r.text
        d = Path(r.json()["experiment_dir"])
        assert c.get("/api/camera/info").json()["nuc_mode"] == "Off"
        meta = json.loads((d / "metadata.json").read_text())
        assert meta["nuc_hold"] == {"mode_before": "Automatic", "nuc_before_start": True}
        time.sleep(0.2)
        c.post("/api/recording/stop")
        assert c.get("/api/camera/info").json()["nuc_mode"] == "Automatic"
        ev = [e["type"] for e in json.loads((d / "events.json").read_text())]
        assert "nuc" in ev  # the pre-record NUC is logged like any other
        # opt out: nothing touched
        r = c.post("/api/recording/start", json={"name": "nohold", "nuc_hold": False})
        assert c.get("/api/camera/info").json()["nuc_mode"] == "Automatic"
        c.post("/api/recording/stop")
        c.post("/api/camera/disconnect")
