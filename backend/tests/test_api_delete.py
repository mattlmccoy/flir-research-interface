"""Deleting a run from the experiment viewer: whole folder removed, never the live recording."""

from __future__ import annotations

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


def test_delete_removes_the_run_folder_and_refuses_the_active_recording(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        d1 = Path(c.post("/api/recording/start", json={"name": "old"}).json()["experiment_dir"])
        time.sleep(0.2)
        c.post("/api/recording/stop")
        d2 = Path(c.post("/api/recording/start", json={"name": "live"}).json()["experiment_dir"])
        time.sleep(0.2)
        r = c.delete(f"/api/experiments/{d2.name}", headers={"X-FRI-Client": "1"})
        assert r.status_code == 409 and d2.is_dir()  # being recorded right now
        r = c.delete(f"/api/experiments/{d1.name}", headers={"X-FRI-Client": "1"})
        assert r.status_code == 200 and r.json() == {"deleted": d1.name}
        assert not d1.exists()
        assert [e["name"] for e in c.get("/api/experiments").json()] == [d2.name]
        c.post("/api/recording/stop")
        c.post("/api/camera/disconnect")
        assert c.delete("/api/experiments/nope").status_code == 404
        # ".." never resolves to a run (the path normalises away)
        assert c.delete("/api/experiments/..").status_code in (400, 404, 405)
        assert tmp_path.is_dir()
