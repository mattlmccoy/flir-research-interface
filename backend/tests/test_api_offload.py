"""Auto-offload end to end: record (simulated camera) on the Mac, stop, and the run moves to the
SSD by itself; with the SSD unplugged or a failing copy, the run stays safely on the Mac.

The "SSD" is a temp folder registered with the real ``register_drive``; the move is the real
``storage.move_experiment``.
"""
from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from collection_helpers import select_collection
from fastapi.testclient import TestClient

from flir_research_interface import storage
from flir_research_interface.api.app import create_app
from flir_research_interface.storage import register_drive


def _app(root: Path) -> TestClient:
    return TestClient(create_app(
        default_backend="simulated", sim_fps=60.0, experiments_root=root, min_free_gb=0.0,
    ))


def _until(pred: Callable[[], Any], timeout: float = 20.0) -> Any:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(0.1)
    raise AssertionError("timeout")


def _record(c: TestClient, name: str = "run") -> Path:
    devs = c.get("/api/camera/devices").json()
    assert c.post("/api/camera/connect",
                  json={"backend": "simulated", "serial": devs[0]["serial"]}).status_code == 200
    r = c.post("/api/recording/start", json={"name": name, "visible": False})
    assert r.status_code == 200, r.text
    exp = Path(r.json()["experiment_dir"])
    _until(lambda: c.get("/api/recording/status").json().get("frames_written", 0) >= 10)
    assert c.post("/api/recording/stop").status_code == 200
    assert c.post("/api/camera/disconnect").status_code == 200
    return exp


def _idle(c: TestClient) -> bool:
    return not c.get("/api/operator/busy").json()["busy"]


@pytest.fixture
def env(tmp_path: Path):  # type: ignore[no-untyped-def]
    root = tmp_path / "experiments"
    root.mkdir()
    mount = tmp_path / "SSD"
    mount.mkdir()
    register_drive(root, str(mount))
    with _app(root) as c:
        select_collection(c, "rf-heating")
        yield root, mount, mount / "FLIR-recordings", c


def test_a_finished_run_moves_to_the_ssd_by_itself(env) -> None:  # type: ignore[no-untyped-def]
    _root, _mount, drive, c = env
    exp = _record(c)
    _until(lambda: _idle(c) and c.get("/api/storage/offload").json()["pending"] == [])
    assert not exp.exists()
    moved = drive / "rf-heating" / exp.name
    assert (moved / "manifest.json").is_file()
    assert (moved / "exports").is_dir()  # post-stop exports finished before the move


def test_ssd_unplugged_keeps_the_run_on_the_mac_until_it_returns(env) -> None:  # type: ignore[no-untyped-def]
    _root, mount, drive, c = env
    hidden = mount.parent / "SSD-away"
    mount.rename(hidden)  # unplug
    exp = _record(c)
    _until(lambda: _idle(c))
    st = c.post("/api/storage/offload/retry").json()
    assert exp.is_dir()
    (e,) = st["pending"]
    assert e["name"] == exp.name and e["state"] == "wait:SSD not connected"
    hidden.rename(mount)  # plug back in
    st = c.post("/api/storage/offload/retry").json()
    assert st["pending"] == []
    assert not exp.exists() and (drive / "rf-heating" / exp.name / "manifest.json").is_file()


def test_a_failed_copy_leaves_the_mac_copy_and_reports(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _root, _mount, drive, c = env

    def boom(*_a: Any, **_k: Any) -> Path:
        raise RuntimeError("copy verification failed: drive went away")

    monkeypatch.setattr(storage, "move_experiment", boom)
    exp = _record(c)
    _until(lambda: _idle(c) and c.get("/api/storage/offload").json()["pending"][0]["attempts"])
    (e,) = c.get("/api/storage/offload").json()["pending"]
    assert "drive went away" in e["error"] and e["attempts"] == 1
    assert e["state"] == "wait:retrying soon"
    assert (exp / "manifest.json").is_file()
    assert not (drive / "rf-heating" / exp.name).exists()


def test_turned_off_means_runs_stay_on_the_mac(env) -> None:  # type: ignore[no-untyped-def]
    _root, _mount, _drive, c = env
    assert c.put("/api/storage/offload", json={"enabled": False}).json()["enabled"] is False
    exp = _record(c)
    _until(lambda: _idle(c))
    c.post("/api/storage/offload/retry")
    assert exp.is_dir()
    assert c.get("/api/storage/offload").json()["pending"] == []  # not queued while off


def test_no_drive_registered_does_nothing(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    root.mkdir()
    with _app(root) as c:
        select_collection(c, "rf-heating")
        exp = _record(c)
        _until(lambda: _idle(c))
        st = c.get("/api/storage/offload").json()
        assert exp.is_dir() and st["pending"] == []
    shutil.rmtree(root)
