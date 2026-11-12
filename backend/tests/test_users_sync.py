"""The user list travels on the SSD: ``FLIR-recordings/.users.json`` mirrors the Mac's copy.

Users files here are hand-made in the shape ``users.py`` writes (no second lab computer exists yet
to capture one from); the tests cover the merge and the sync points, not real lab data.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.storage import register_drive
from flir_research_interface.users import USERS_FILE, merge_users

PROFILE = {"name": "Laser", "fields": [], "marks": [{"label": "laser on", "key": "l"}]}


def _setup(tmp_path: Path) -> tuple[Path, Path, TestClient]:
    root = tmp_path / "experiments"
    root.mkdir()
    mount = tmp_path / "SSD"
    mount.mkdir()
    register_drive(root, str(mount))
    app = create_app(default_backend="simulated", experiments_root=root, min_free_gb=0.0)
    return root, mount / "FLIR-recordings", TestClient(app)


def _user(uid: str, name: str, updated: float, profile_name: str = "default") -> dict:
    return {"id": uid, "name": name, "collections": [uid], "last_collection": uid,
            "profile": {"name": profile_name, "fields": [], "marks": []}, "updated": updated}


def test_merge_is_a_union_and_the_newer_edit_wins() -> None:
    a = [_user("matt", "Matt", 10.0, "RF"), _user("ana", "Ana", 5.0)]
    b = [_user("matt", "Matt", 20.0, "RF v2"), _user("li", "Li", 1.0)]
    merged = {u["id"]: u for u in merge_users(a, b)}
    assert set(merged) == {"matt", "ana", "li"}
    assert merged["matt"]["profile"]["name"] == "RF v2"
    assert [u["id"] for u in merge_users(a, b)] == ["matt", "ana", "li"]  # stable order


def test_users_on_the_ssd_appear_on_this_mac(tmp_path: Path) -> None:
    root, drive, c = _setup(tmp_path)
    ana = [_user("ana", "Ana", 1.0)]
    (drive / USERS_FILE).write_text(json.dumps({"current": None, "users": ana}))
    doc = c.get("/api/users").json()
    assert [u["id"] for u in doc["users"]] == ["ana"]
    assert doc["current"] is None
    assert json.loads((root / USERS_FILE).read_text())["users"][0]["id"] == "ana"


def test_adding_a_person_writes_the_ssd_copy_and_folder(tmp_path: Path) -> None:
    root, drive, c = _setup(tmp_path)
    assert c.post("/api/users", json={"name": "Matt McCoy"}).status_code == 200
    assert c.put("/api/users/current", json={"id": "mattmccoy"}).status_code == 200
    on_ssd = json.loads((drive / USERS_FILE).read_text())
    assert [u["id"] for u in on_ssd["users"]] == ["mattmccoy"]
    assert on_ssd["current"] is None  # who is at the bench stays on each computer
    assert (drive / "mattmccoy").is_dir()


def test_profile_edits_reach_the_ssd(tmp_path: Path) -> None:
    _root, drive, c = _setup(tmp_path)
    c.post("/api/users", json={"name": "Ana"})
    c.put("/api/users/current", json={"id": "ana"})
    assert c.put("/api/profile", json=PROFILE).status_code == 200
    on_ssd = json.loads((drive / USERS_FILE).read_text())
    assert on_ssd["users"][0]["profile"]["name"] == "Laser"


def test_newer_ssd_edit_replaces_an_older_local_one(tmp_path: Path) -> None:
    root, drive, c = _setup(tmp_path)
    old = [_user("ana", "Ana", 1.0, "old")]
    new = [_user("ana", "Ana", 9.0, "new")]
    (root / USERS_FILE).write_text(json.dumps({"current": "ana", "users": old}))
    (drive / USERS_FILE).write_text(json.dumps({"current": None, "users": new}))
    doc = c.get("/api/users").json()
    assert doc["users"][0]["profile_name"] == "new"
    assert doc["current"] == "ana"


def test_an_unreadable_ssd_copy_is_left_alone(tmp_path: Path) -> None:
    root, drive, c = _setup(tmp_path)
    (drive / USERS_FILE).write_text("{broken")
    assert c.post("/api/users", json={"name": "Ana"}).status_code == 200
    assert (drive / USERS_FILE).read_text() == "{broken"
    assert [u["id"] for u in c.get("/api/users").json()["users"]] == ["ana"]


def test_works_with_the_ssd_unplugged(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    app = create_app(default_backend="simulated", experiments_root=root, min_free_gb=0.0)
    c = TestClient(app)
    assert c.post("/api/users", json={"name": "Ana"}).status_code == 200
    assert [u["id"] for u in c.get("/api/users").json()["users"]] == ["ana"]
