"""Storage API: union list across local+drive, register a drive, and the offload move job."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app


def _client(local: Path) -> TestClient:
    return TestClient(
        create_app(
            default_backend="simulated", sim_fps=60.0, experiments_root=local, min_free_gb=0.0
        )
    )


def _record(c: TestClient) -> str:
    devs = c.get("/api/camera/devices").json()
    c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
    name = Path(c.post("/api/recording/start", json={"name": "run"}).json()["experiment_dir"]).name
    time.sleep(0.25)
    c.post("/api/recording/stop")
    return name


def _wait_move(c: TestClient, name: str, timeout: float = 30.0) -> dict:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        job = c.get(f"/api/experiments/{name}/move/status").json()
        if job["state"] in ("done", "error"):
            return job
        time.sleep(0.1)
    raise AssertionError("move did not finish")


def test_register_drive_and_state(tmp_path: Path) -> None:
    local = tmp_path / "local"
    local.mkdir()
    drive = tmp_path / "Field"
    drive.mkdir()
    with _client(local) as c:
        assert c.get("/api/storage").json()["drive"] is None
        r = c.put("/api/storage/drive", json={"mount": str(drive)})
        assert r.status_code == 200, r.text
        st = r.json()
        assert st["drive"]["mount"] == str(drive) and st["drive"]["connected"] is True
        assert (drive / "FLIR-recordings").is_dir()
        assert c.delete("/api/storage/drive").json()["drive"] is None


def test_move_to_drive_unions_list_and_frees_local(tmp_path: Path) -> None:
    local = tmp_path / "local"
    local.mkdir()
    drive = tmp_path / "Field"
    drive.mkdir()
    with _client(local) as c:
        name = _record(c)
        c.post("/api/camera/disconnect")
        c.put("/api/storage/drive", json={"mount": str(drive)})

        r = c.post(f"/api/experiments/{name}/move", json={"to": "drive"})
        assert r.json()["state"] == "running"
        job = _wait_move(c, name)
        assert job["state"] == "done", job

        # gone from local, present on the drive, still one run in the unioned list
        assert not (local / name).exists()
        assert (drive / "FLIR-recordings" / name / "metadata.json").is_file()
        items = c.get("/api/experiments").json()
        libs = {e["name"]: e["library"] for e in items}
        assert libs.get(name) == "drive"
        # a run on the drive is still openable (resolved across roots)
        assert c.get(f"/api/experiments/{name}").status_code == 200

        # and it can be brought back
        back = c.post(f"/api/experiments/{name}/move", json={"to": "local"})
        assert back.json()["state"] == "running"
        assert _wait_move(c, name)["state"] == "done"
        assert (local / name / "metadata.json").is_file()


def test_move_without_drive_is_409_and_unknown_run_404(tmp_path: Path) -> None:
    local = tmp_path / "local"
    local.mkdir()
    with _client(local) as c:
        name = _record(c)
        c.post("/api/camera/disconnect")
        assert c.post(f"/api/experiments/{name}/move", json={"to": "drive"}).status_code == 409
        assert c.post("/api/experiments/nope/move", json={"to": "drive"}).status_code == 404
