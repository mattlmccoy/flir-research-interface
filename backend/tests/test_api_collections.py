"""Collections API and per-collection listing.

Runs here are hand-made (``mkdir`` + ``metadata.json``), not captured from a real recording; the
tests cover folder classification and routing, not run contents.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.collections import SELECTION_FILE
from flir_research_interface.storage import register_drive


def _client(root: Path) -> TestClient:
    app = create_app(default_backend="simulated", experiments_root=root, min_free_gb=0.0)
    return TestClient(app)


def _run(parent: Path, name: str) -> Path:
    d = parent / name
    d.mkdir(parents=True)
    (d / "metadata.json").write_text(json.dumps({"experiment": {"name": name}}))
    return d


def test_collections_doc_shows_everything(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    (root / "mattmccoy").mkdir(parents=True)
    _run(root, "20260101_000000_a")
    (root / "Old Stuff").mkdir()
    drive = tmp_path / "Drive"
    drive.mkdir()
    register_drive(root, str(drive))
    (drive / "FLIR-recordings" / "rf-sintering").mkdir()

    doc = _client(root).get("/api/collections").json()

    assert doc["collections"] == [
        {"name": "mattmccoy", "local": True, "drive": False, "offline": False},
        {"name": "rf-sintering", "local": False, "drive": True, "offline": False},
    ]
    assert doc["unsorted"] == {"local": 1, "drive": 0}
    assert {"library": "local", "name": "Old Stuff"} in doc["unexpected"]
    assert doc["selected"] is None
    assert doc["drive_connected"] is True


def test_add_collection_validates_and_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    c = _client(root)
    assert c.post("/api/collections", json={"name": "Bad Name"}).status_code == 400
    for _ in range(2):
        r = c.post("/api/collections", json={"name": "rf-sintering"})
        assert r.status_code == 200
        assert r.json()["collections"][0]["name"] == "rf-sintering"
    assert (root / "rf-sintering").is_dir()


def test_select_persists_on_operator(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    (root / "mattmccoy").mkdir(parents=True)
    c = _client(root)
    r = c.put("/api/collections/selected", json={"name": "mattmccoy"})
    assert r.status_code == 200 and r.json()["selected"] == "mattmccoy"
    assert json.loads((root / SELECTION_FILE).read_text()) == {"selected": "mattmccoy"}
    assert _client(root).get("/api/collections").json()["selected"] == "mattmccoy"
    assert c.put("/api/collections/selected", json={"name": "nope"}).status_code == 404
    assert c.put("/api/collections/selected", json={"name": "Bad Name"}).status_code == 400


def test_listing_scoped_to_collection(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    _run(root / "mattmccoy", "20260101_000000_in")
    _run(root, "20260102_000000_top")
    c = _client(root)
    items = c.get("/api/experiments", params={"collection": "mattmccoy"}).json()
    assert [(i["name"], i["collection"]) for i in items] == [("20260101_000000_in", "mattmccoy")]
    c.put("/api/collections/selected", json={"name": "mattmccoy"})
    assert [i["name"] for i in c.get("/api/experiments").json()] == ["20260101_000000_in"]
    summary = c.get("/api/experiments/summary", params={"collection": "mattmccoy"}).json()
    assert summary["count"] == 1
    assert c.get("/api/experiments", params={"collection": "Bad Name"}).status_code == 400


def test_unsorted_listing_excludes_collection_folders(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    (root / "mattmccoy").mkdir(parents=True)
    (root / "Old Stuff").mkdir()
    _run(root, "20260102_000000_top")
    c = _client(root)
    items = c.get("/api/experiments", params={"collection": ""}).json()
    assert [i["name"] for i in items] == ["20260102_000000_top"]
    assert items[0]["collection"] is None
