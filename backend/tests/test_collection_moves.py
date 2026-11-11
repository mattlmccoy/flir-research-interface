"""Moves keep the run's collection; name clashes are refused; move a run into a collection (Task 6).

Runs are recorded with the simulated camera (real run folders). The pre-created clash folders and
the ``._<run>`` AppleDouble sibling are hand-made shapes: an empty folder standing in for an
existing run, an uppercased name mimicking exFAT case-insensitivity, and the sidecar exFAT leaves
next to a renamed folder.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from collection_helpers import select_collection
from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app


def _client(local: Path) -> TestClient:
    return TestClient(
        create_app(
            default_backend="simulated", sim_fps=60.0, experiments_root=local, min_free_gb=0.0
        )
    )


def _record(c: TestClient, collection: str = "mattmccoy") -> str:
    devs = c.get("/api/camera/devices").json()
    c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
    select_collection(c, collection)
    r = c.post("/api/recording/start", json={"name": "run"})
    assert r.status_code == 200, r.text
    name = Path(r.json()["experiment_dir"]).name
    time.sleep(0.25)
    c.post("/api/recording/stop")
    c.post("/api/camera/disconnect")
    t0 = time.monotonic()  # let the post-stop exports finish, so folder listings are stable
    while c.app.state.render_tasks and time.monotonic() - t0 < 30.0:  # type: ignore[attr-defined]
        time.sleep(0.05)
    assert not c.app.state.render_tasks  # type: ignore[attr-defined]
    return name


def _wait_move(c: TestClient, name: str, collection: str, timeout: float = 30.0) -> dict:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        job = c.get(f"/api/experiments/{name}/move/status?collection={collection}").json()
        if job["state"] in ("done", "error"):
            return job
        time.sleep(0.1)
    raise AssertionError("move did not finish")


def _listing(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    local, drive = tmp_path / "local", tmp_path / "Drive"
    local.mkdir()
    drive.mkdir()
    return local, drive


def test_move_to_drive_keeps_collection(tmp_path: Path) -> None:
    local, drive = _setup(tmp_path)
    with _client(local) as c:
        name = _record(c)
        assert c.put("/api/storage/drive", json={"mount": str(drive)}).status_code == 200
        r = c.post(f"/api/experiments/{name}/move?collection=mattmccoy", json={"to": "drive"})
        assert r.status_code == 200, r.text
        assert _wait_move(c, name, "mattmccoy")["state"] == "done"
        assert (drive / "FLIR-recordings" / "mattmccoy").is_dir()
        assert (drive / "FLIR-recordings" / "mattmccoy" / name / "metadata.json").is_file()
        assert not (local / "mattmccoy" / name).exists()

        back = c.post(f"/api/experiments/{name}/move?collection=mattmccoy", json={"to": "local"})
        assert back.status_code == 200, back.text
        assert _wait_move(c, name, "mattmccoy")["state"] == "done"
        assert (local / "mattmccoy" / name / "metadata.json").is_file()
        assert not (drive / "FLIR-recordings" / "mattmccoy" / name).exists()


def test_move_to_drive_refuses_existing_name(tmp_path: Path) -> None:
    local, drive = _setup(tmp_path)
    with _client(local) as c:
        name = _record(c)
        c.put("/api/storage/drive", json={"mount": str(drive)})
        (drive / "FLIR-recordings" / "mattmccoy" / name).mkdir(parents=True)  # hand-made clash
        before = (_listing(local), _listing(drive))
        r = c.post(f"/api/experiments/{name}/move?collection=mattmccoy", json={"to": "drive"})
        assert r.status_code == 409
        assert r.json()["detail"] == (
            f"mattmccoy on the drive already has a run named {name}; nothing was moved"
        )
        assert c.get(f"/api/experiments/{name}/move/status?collection=mattmccoy").json() == {
            "state": "idle"
        }
        assert (_listing(local), _listing(drive)) == before


def test_move_refuses_casefold_clash(tmp_path: Path) -> None:
    local, drive = _setup(tmp_path)
    with _client(local) as c:
        name = _record(c)
        c.put("/api/storage/drive", json={"mount": str(drive)})
        # hand-made: an uppercased twin, as exFAT would treat the two names as the same entry
        (drive / "FLIR-recordings" / "mattmccoy" / name.upper()).mkdir(parents=True)
        before = (_listing(local), _listing(drive))
        r = c.post(f"/api/experiments/{name}/move?collection=mattmccoy", json={"to": "drive"})
        assert r.status_code == 409, r.text
        assert r.json()["detail"] == (
            f"mattmccoy on the drive already has a run named {name}; nothing was moved"
        )
        assert (_listing(local), _listing(drive)) == before


def _unsorted_run(c: TestClient, local: Path) -> str:
    """A real recorded run, renamed to the top level (Unsorted)."""
    name = _record(c, "t")
    os.rename(local / "t" / name, local / name)
    return name


def test_move_into_collection_from_unsorted(tmp_path: Path) -> None:
    local, _drive = _setup(tmp_path)
    with _client(local) as c:
        name = _unsorted_run(c, local)
        (local / f"._{name}").write_bytes(b"\x00\x05\x16\x07")  # hand-made AppleDouble sidecar
        r = c.post(f"/api/experiments/{name}/collection?collection=", json={"to": "mattmccoy"})
        assert r.status_code == 200, r.text
        assert r.json() == {"collection": "mattmccoy", "name": name}
        assert (local / "mattmccoy" / name / "metadata.json").is_file()
        assert not (local / name).exists()
        assert not (local / f"._{name}").exists()

        # and back to Unsorted
        r = c.post(f"/api/experiments/{name}/collection?collection=mattmccoy", json={"to": ""})
        assert r.status_code == 200, r.text
        assert r.json() == {"collection": None, "name": name}
        assert (local / name / "metadata.json").is_file()


def test_move_into_collection_refuses_clash(tmp_path: Path) -> None:
    local, _drive = _setup(tmp_path)
    with _client(local) as c:
        name = _unsorted_run(c, local)
        (local / "mattmccoy" / name).mkdir(parents=True)  # hand-made clash
        r = c.post(f"/api/experiments/{name}/collection?collection=", json={"to": "mattmccoy"})
        assert r.status_code == 409
        assert r.json()["detail"] == (
            f"mattmccoy on this Mac already has a run named {name}; nothing was moved"
        )
        assert (local / name / "metadata.json").is_file()


def test_move_into_collection_rejects_invalid_name(tmp_path: Path) -> None:
    local, _drive = _setup(tmp_path)
    with _client(local) as c:
        name = _unsorted_run(c, local)
        r = c.post(f"/api/experiments/{name}/collection?collection=", json={"to": "Bad Name"})
        assert r.status_code == 400
        assert (local / name).is_dir()


def test_move_into_collection_refuses_busy_run(tmp_path: Path) -> None:
    local, _drive = _setup(tmp_path)
    with _client(local) as c:
        name = _unsorted_run(c, local)
        lock = c.app.state.render_locks.get(name)  # type: ignore[attr-defined]
        c.portal.call(lock.acquire)  # type: ignore[union-attr]
        try:
            r = c.post(f"/api/experiments/{name}/collection?collection=", json={"to": "mattmccoy"})
            assert r.status_code == 409, r.text
            assert (local / name).is_dir()
        finally:
            c.portal.call(lock.release)  # type: ignore[union-attr]


def test_move_into_collection_refuses_running_job(tmp_path: Path) -> None:
    local, _drive = _setup(tmp_path)
    with _client(local) as c:
        name = _unsorted_run(c, local)
        # hand-made: job records as the routes write them, scheduled but not yet holding the lock
        jobs = {"move_jobs": name, "derived_jobs": name, "smart_jobs": (name, "roi1")}
        for attr, key in jobs.items():
            table = getattr(c.app.state, attr)  # type: ignore[attr-defined]
            table[key] = {"state": "running"}
            r = c.post(f"/api/experiments/{name}/collection?collection=", json={"to": "mattmccoy"})
            assert r.status_code == 409, (attr, r.text)
            del table[key]
        assert (local / name).is_dir()


def test_move_into_collection_refuses_while_stopping(tmp_path: Path) -> None:
    local, _drive = _setup(tmp_path)
    with _client(local) as c:
        name = _unsorted_run(c, local)
        # hand-made: the dir _finalize_recording registers while the visible recorder stops
        c.app.state.stopping_dirs.add((local / name).resolve())  # type: ignore[attr-defined]
        r = c.post(f"/api/experiments/{name}/collection?collection=", json={"to": "mattmccoy"})
        assert r.status_code == 409, r.text
        assert (local / name).is_dir()
        assert "finishing a recording" in c.get("/api/operator/busy").json()["reasons"]


def test_move_into_own_collection_is_400(tmp_path: Path) -> None:
    local, _drive = _setup(tmp_path)
    with _client(local) as c:
        name = _record(c)
        url = f"/api/experiments/{name}/collection?collection=mattmccoy"
        r = c.post(url, json={"to": "mattmccoy"})
        assert r.status_code == 400
        assert r.json()["detail"] == "already in mattmccoy"
        assert (local / "mattmccoy" / name).is_dir()


def test_move_into_collection_refuses_running_move_to_destination(tmp_path: Path) -> None:
    local, _drive = _setup(tmp_path)
    with _client(local) as c:
        name = _unsorted_run(c, local)
        # hand-made: a move job record for the destination key, as the move route writes it
        c.app.state.move_jobs[f"mattmccoy/{name}"] = {"state": "running"}  # type: ignore[attr-defined]
        r = c.post(f"/api/experiments/{name}/collection?collection=", json={"to": "mattmccoy"})
        assert r.status_code == 409, r.text
        assert (local / name).is_dir()


def test_move_top_level_run_clash_says_unsorted(tmp_path: Path) -> None:
    local, drive = _setup(tmp_path)
    with _client(local) as c:
        name = _unsorted_run(c, local)
        c.put("/api/storage/drive", json={"mount": str(drive)})
        (drive / "FLIR-recordings" / name).mkdir(parents=True)  # hand-made clash
        r = c.post(f"/api/experiments/{name}/move?collection=", json={"to": "drive"})
        assert r.status_code == 409
        assert r.json()["detail"] == (
            f"Unsorted on the drive already has a run named {name}; nothing was moved"
        )


def test_move_into_collection_removes_new_dir_when_rename_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from flir_research_interface import storage

    run = tmp_path / "root" / "20261111_120000_run"  # hand-made run folder
    run.mkdir(parents=True)

    def _fail(_a: object, _b: object) -> None:
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(storage.os, "rename", _fail)
    with pytest.raises(OSError):
        storage.move_into_collection(run, tmp_path / "root", "mattmccoy")
    assert not (tmp_path / "root" / "mattmccoy").exists()
    assert run.is_dir()
