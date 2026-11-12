"""Renaming a collection: one folder rename per volume, plus every reference to the old name.

Runs are hand-made (``mkdir`` + ``metadata.json``); the drive index is written by the real
``remember_drive_runs``. The tests cover renaming and bookkeeping, not run contents.
"""
from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.collections import load_selection
from flir_research_interface.storage import (
    INDEX_NAME,
    offline_index,
    register_drive,
    remember_drive_runs,
)
from flir_research_interface.users import USERS_FILE


def _run(parent: Path, name: str) -> Path:
    d = parent / name
    d.mkdir(parents=True)
    (d / "metadata.json").write_text(json.dumps({"experiment": {"name": name}}))
    return d


def _client(root: Path) -> TestClient:
    app = create_app(default_backend="simulated", experiments_root=root, min_free_gb=0.0)
    return TestClient(app)


Env = tuple[Path, Path, Path, TestClient]


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    """A started operator (lifespan running, as in production) with a registered SSD."""
    root = tmp_path / "experiments"
    root.mkdir()
    mount = tmp_path / "SSD"
    mount.mkdir()
    register_drive(root, str(mount))
    with _client(root) as c:
        yield root, mount, mount / "FLIR-recordings", c


def test_rename_moves_folders_on_both_volumes(env: Env) -> None:
    root, _mount, drive, c = env
    _run(root / "old-proj", "20260101_000000_a")
    _run(drive / "old-proj", "20260102_000000_b")
    r = c.post("/api/collections/rename", json={"old": "old-proj", "new": "new-proj"})
    assert r.status_code == 200, r.text
    assert (root / "new-proj" / "20260101_000000_a").is_dir()
    assert (drive / "new-proj" / "20260102_000000_b").is_dir()
    assert not (root / "old-proj").exists() and not (drive / "old-proj").exists()
    names = [x["name"] for x in r.json()["collections"]]
    assert "new-proj" in names and "old-proj" not in names


def test_rename_updates_selection_users_and_rename_log(env: Env) -> None:
    root, _mount, drive, c = env
    c.post("/api/users", json={"name": "Matt McCoy"})
    c.post("/api/users", json={"name": "Ana", "collection": "mattmccoy"})
    c.put("/api/users/current", json={"id": "mattmccoy"})
    r = c.post("/api/collections/rename", json={"old": "mattmccoy", "new": "rf-heating"})
    assert r.status_code == 200, r.text
    assert load_selection(root) == "rf-heating"
    for u in c.get("/api/users").json()["users"]:
        assert u["collections"] == ["rf-heating"] and u["last_collection"] == "rf-heating"
    on_ssd = json.loads((drive / USERS_FILE).read_text())
    assert all(u["collections"] == ["rf-heating"] for u in on_ssd["users"])
    assert c.get("/api/collections").json()["renames"][-1]["from"] == "mattmccoy"
    assert c.get("/api/collections").json()["renames"][-1]["to"] == "rf-heating"


def test_rename_rewrites_the_drive_index(env: Env) -> None:
    root, _mount, drive, c = env
    run = _run(drive / "old-proj", "20260102_000000_b")
    entry = {"name": run.name, "path": str(run)}
    remember_drive_runs(root, [entry], "SSD", collection="old-proj")
    r = c.post("/api/collections/rename", json={"old": "old-proj", "new": "new-proj"})
    assert r.status_code == 200, r.text
    (entry,) = offline_index(root)
    assert entry["collection"] == "new-proj"
    assert entry["path"] == str(drive / "new-proj" / run.name)
    assert (root / INDEX_NAME).is_file()


def test_rename_refuses_bad_or_clashing_names(env: Env) -> None:
    root, _mount, drive, c = env
    (root / "a").mkdir()
    (drive / "b").mkdir()
    bad = c.post("/api/collections/rename", json={"old": "a", "new": "Bad Name"})
    assert bad.status_code == 400
    assert c.post("/api/collections/rename", json={"old": "a", "new": "a"}).status_code == 400
    assert c.post("/api/collections/rename", json={"old": "a", "new": "b"}).status_code == 409
    assert c.post("/api/collections/rename", json={"old": "nope", "new": "c"}).status_code == 404
    assert (root / "a").is_dir()


def test_rename_refused_while_the_ssd_holding_it_is_unplugged(env: Env) -> None:
    root, mount, drive, c = env
    run = _run(drive / "old-proj", "20260102_000000_b")
    entry = {"name": run.name, "path": str(run)}
    remember_drive_runs(root, [entry], "SSD", collection="old-proj")
    (root / "old-proj").mkdir()
    # unplug: the mount disappears
    shutil.rmtree(mount)
    r = c.post("/api/collections/rename", json={"old": "old-proj", "new": "new-proj"})
    assert r.status_code == 409
    assert "plug in" in r.json()["detail"].lower()
    assert (root / "old-proj").is_dir()


def test_rename_refused_while_busy(env: Env) -> None:
    root, _mount, _drive, c = env
    (root / "a").mkdir()
    devs = c.get("/api/camera/devices").json()
    c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
    c.put("/api/collections/selected", json={"name": "a"})
    assert c.post("/api/recording/start", json={"name": "x"}).status_code == 200
    r = c.post("/api/collections/rename", json={"old": "a", "new": "b"})
    assert r.status_code == 409
    assert c.post("/api/recording/stop").status_code == 200
    assert (root / "a").is_dir()


def test_rename_rolls_back_the_mac_when_the_ssd_rename_fails(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _mount, drive, c = env
    (root / "a").mkdir()
    (drive / "a").mkdir()
    real = os.rename

    def flaky(src: Path, dst: Path) -> None:
        if str(src).startswith(str(drive)):
            raise OSError("drive went away")
        return real(src, dst)

    monkeypatch.setattr(os, "rename", flaky)
    r = c.post("/api/collections/rename", json={"old": "a", "new": "b"})
    assert r.status_code == 500
    assert (root / "a").is_dir() and not (root / "b").exists()
    assert (drive / "a").is_dir()
