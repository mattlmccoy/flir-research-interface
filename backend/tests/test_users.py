"""User profiles: who is at the bench, their shared collections and their own project profile.

Users are hand-made through the API (no real users file exists yet to capture); the tests cover
the file model and routing, not lab data.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flir_research_interface.analysis.calibration import calibration_dir
from flir_research_interface.analysis.profile import DEFAULT_PROFILE, save_profile
from flir_research_interface.api.app import create_app
from flir_research_interface.collections import load_selection
from flir_research_interface.users import USERS_FILE, slug_for, user_id_error


def _client(root: Path) -> TestClient:
    app = create_app(default_backend="simulated", experiments_root=root, min_free_gb=0.0)
    return TestClient(app)


RF = {"name": "RF heating", "fields": [{"key": "power_w", "label": "Power (W)", "type": "number"}],
      "marks": [{"label": "RF on", "key": "r"}]}


def test_slug_for_names() -> None:
    assert slug_for("Matt McCoy") == "mattmccoy"
    assert slug_for("  Ana Ruiz-Lopez ") == "anaruiz-lopez"
    assert slug_for("José") == "jose"
    assert slug_for("!!!") == ""


def test_user_id_error_matches_collection_rules() -> None:
    assert user_id_error("mattmccoy") is None
    assert user_id_error("Bad Name") is not None
    assert user_id_error("20260101_000000") is not None


def test_no_users_file_means_no_current_user(tmp_path: Path) -> None:
    doc = _client(tmp_path / "exp").get("/api/users").json()
    assert doc == {"current": None, "users": []}


def test_add_user_creates_their_collection_and_copies_the_lab_profile(tmp_path: Path) -> None:
    root = tmp_path / "exp"
    save_profile(root, RF)
    c = _client(root)
    r = c.post("/api/users", json={"name": "Matt McCoy"})
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["users"] == [{"id": "mattmccoy", "name": "Matt McCoy", "collections": ["mattmccoy"],
                             "last_collection": "mattmccoy", "profile_name": "RF heating"}]
    assert (root / "mattmccoy").is_dir()
    assert (root / USERS_FILE).is_file()


def test_add_user_rejects_duplicates_and_unnameable(tmp_path: Path) -> None:
    c = _client(tmp_path / "exp")
    assert c.post("/api/users", json={"name": "Matt McCoy"}).status_code == 200
    assert c.post("/api/users", json={"name": "matt mccoy"}).status_code == 409
    assert c.post("/api/users", json={"name": "!!!"}).status_code == 400
    assert c.post("/api/users", json={"name": "x" * 61}).status_code == 400


def test_add_user_with_existing_collection(tmp_path: Path) -> None:
    root = tmp_path / "exp"
    c = _client(root)
    c.post("/api/collections", json={"name": "rf-sintering"})
    r = c.post("/api/users", json={"name": "Ana", "collection": "rf-sintering"})
    assert r.json()["users"][0]["collections"] == ["rf-sintering"]
    assert not (root / "ana").exists()


def test_switch_user_selects_their_last_collection_and_is_remembered(tmp_path: Path) -> None:
    root = tmp_path / "exp"
    c = _client(root)
    c.post("/api/users", json={"name": "Matt McCoy"})
    c.post("/api/users", json={"name": "Ana"})
    r = c.put("/api/users/current", json={"id": "ana"})
    assert r.status_code == 200
    assert r.json()["current"] == "ana"
    assert load_selection(root) == "ana"
    c.put("/api/users/current", json={"id": "mattmccoy"})
    assert load_selection(root) == "mattmccoy"
    # a fresh operator (restart) remembers the last user
    assert _client(root).get("/api/users").json()["current"] == "mattmccoy"


def test_switch_to_unknown_user_404(tmp_path: Path) -> None:
    c = _client(tmp_path / "exp")
    assert c.put("/api/users/current", json={"id": "nobody"}).status_code == 404


def test_selecting_a_collection_joins_it_to_the_current_user(tmp_path: Path) -> None:
    root = tmp_path / "exp"
    c = _client(root)
    c.post("/api/users", json={"name": "Matt McCoy"})
    c.put("/api/users/current", json={"id": "mattmccoy"})
    c.post("/api/collections", json={"name": "rf-sintering"})
    assert c.put("/api/collections/selected", json={"name": "rf-sintering"}).status_code == 200
    u = c.get("/api/users").json()["users"][0]
    assert u["collections"] == ["mattmccoy", "rf-sintering"]
    assert u["last_collection"] == "rf-sintering"
    # switching away and back returns to the collection they used last
    c.post("/api/users", json={"name": "Ana"})
    c.put("/api/users/current", json={"id": "ana"})
    c.put("/api/users/current", json={"id": "mattmccoy"})
    assert load_selection(root) == "rf-sintering"


def test_profile_follows_the_current_user(tmp_path: Path) -> None:
    root = tmp_path / "exp"
    save_profile(root, RF)
    c = _client(root)
    c.post("/api/users", json={"name": "Matt McCoy"})
    c.post("/api/users", json={"name": "Ana"})
    c.put("/api/users/current", json={"id": "ana"})
    ana = {"name": "Laser", "fields": [], "marks": [{"label": "laser on", "key": "l"}]}
    assert c.put("/api/profile", json=ana).status_code == 200
    assert c.get("/api/profile").json()["name"] == "Laser"
    c.put("/api/users/current", json={"id": "mattmccoy"})
    assert c.get("/api/profile").json()["name"] == "RF heating"
    # the shared lab template is untouched by per-user edits
    shared = json.loads((calibration_dir(root) / "profile.json").read_text())
    assert shared["name"] == "RF heating"


def test_profile_without_users_still_uses_the_shared_file(tmp_path: Path) -> None:
    root = tmp_path / "exp"
    c = _client(root)
    assert c.get("/api/profile").json()["name"] == DEFAULT_PROFILE["name"]
    assert c.put("/api/profile", json=RF).status_code == 200
    assert json.loads((calibration_dir(root) / "profile.json").read_text())["name"] == "RF heating"


def test_malformed_users_file_reads_as_empty(tmp_path: Path) -> None:
    root = tmp_path / "exp"
    root.mkdir()
    (root / USERS_FILE).write_text("{not json")
    assert _client(root).get("/api/users").json() == {"current": None, "users": []}


@pytest.mark.parametrize("bad", ["../x", "", "Bad"])
def test_switch_rejects_bad_ids(tmp_path: Path, bad: str) -> None:
    c = _client(tmp_path / "exp")
    assert c.put("/api/users/current", json={"id": bad}).status_code in (400, 404)
