"""Drive index v2: one offline index that keeps every collection's runs (Task 7).

The v1 index is the captured fixture ``drive_index_v1_20261109.json`` (real ``.drive-index.json``,
redacted). v2 entries are derived from it by adding ``collection`` (the v2 shape written by
``storage.remember_drive_runs``). Run folders made with ``mkdir`` + ``metadata.json`` are
hand-made; they cover routing, not run contents.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from flir_research_interface import storage
from flir_research_interface.api.app import create_app

FIXTURE = Path(__file__).parent / "fixtures" / "drive_index_v1_20261109.json"


def _v1() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


def _local(tmp_path: Path) -> Path:
    local = tmp_path / "local"
    local.mkdir()
    return local


def _index(local: Path) -> dict[str, Any]:
    return json.loads((local / storage.INDEX_NAME).read_text())


def test_v1_index_reads_as_top_level(tmp_path: Path) -> None:
    local = _local(tmp_path)
    shutil.copy(FIXTURE, local / storage.INDEX_NAME)

    top = storage.offline_runs(local, collection=None)
    assert [r["name"] for r in top] == [r["name"] for r in _v1()["runs"]]
    assert all(r["collection"] is None and r["library"] == "offline" for r in top)
    assert storage.offline_runs(local, collection="mattmccoy") == []
    assert storage.offline_collections(local) == set()


def test_remember_one_collection_keeps_others(tmp_path: Path) -> None:
    local = _local(tmp_path)
    shutil.copy(FIXTURE, local / storage.INDEX_NAME)
    v1_names = sorted(r["name"] for r in _v1()["runs"])
    run = {**_v1()["runs"][0], "name": "20261110_090000_m", "library": "drive", "root": "/x"}

    storage.remember_drive_runs(local, [run], "FLIR SSD", collection="mattmccoy")
    idx = _index(local)
    assert idx["schema"] == 2
    assert [(r["collection"], r["name"]) for r in idx["runs"]] == [
        *((None, n) for n in v1_names), ("mattmccoy", "20261110_090000_m"),
    ]
    assert "root" not in idx["runs"][-1] and "library" not in idx["runs"][-1]
    assert storage.offline_collections(local) == {"mattmccoy"}
    assert [r["name"] for r in storage.offline_runs(local, collection="mattmccoy")] == [
        "20261110_090000_m"
    ]

    stamp = (local / storage.INDEX_NAME).stat().st_mtime_ns
    time.sleep(0.01)
    storage.remember_drive_runs(local, [run], "FLIR SSD", collection="mattmccoy")
    assert (local / storage.INDEX_NAME).stat().st_mtime_ns == stamp, "unchanged: not rewritten"

    storage.remember_drive_runs(local, [], "FLIR SSD", collection="mattmccoy")
    idx = _index(local)
    assert [(r["collection"], r["name"]) for r in idx["runs"]] == [(None, n) for n in v1_names]
    assert storage.offline_collections(local) == set()


def _unplugged(tmp_path: Path) -> Path:
    """Local root with a registered drive that is now unplugged, and a v2 index (derived from the
    captured v1 fixture) whose runs belong to ``rf-sintering``."""
    local = _local(tmp_path)
    drive = tmp_path / "Drive"
    drive.mkdir()
    storage.register_drive(local, str(drive))
    shutil.rmtree(drive)  # unplugged
    idx = _v1()
    idx["schema"] = 2
    idx["runs"] = [{**r, "collection": "rf-sintering"} for r in idx["runs"]]
    (local / storage.INDEX_NAME).write_text(json.dumps(idx))
    return local


def _client(local: Path) -> TestClient:
    return TestClient(
        create_app(
            default_backend="simulated", sim_fps=60.0, experiments_root=local, min_free_gb=0.0
        )
    )


def test_offline_collection_listed_and_browsable(tmp_path: Path) -> None:
    local = _unplugged(tmp_path)
    (local / "mattmccoy").mkdir()  # local only: the index has nothing for it
    c = _client(local)

    doc = c.get("/api/collections").json()
    assert doc["collections"] == [
        {"name": "mattmccoy", "local": True, "drive": False, "offline": False},
        {"name": "rf-sintering", "local": False, "drive": True, "offline": True},
    ]
    assert doc["drive_connected"] is False and doc["drive_registered"] is True

    cards = c.get("/api/experiments", params={"collection": "rf-sintering"}).json()
    assert sorted(it["name"] for it in cards) == sorted(r["name"] for r in _v1()["runs"])
    assert all(it["offline"] is True and it["collection"] == "rf-sintering" for it in cards)
    assert c.get("/api/experiments", params={"collection": ""}).json() == []
    assert c.get("/api/experiments", params={"collection": "mattmccoy"}).json() == []

    locs = c.get("/api/collections/runs").json()
    assert {(r["collection"], r["name"]) for r in locs} == {
        ("rf-sintering", r["name"]) for r in _v1()["runs"]
    }


def test_local_collection_known_to_index_is_marked_offline(tmp_path: Path) -> None:
    local = _unplugged(tmp_path)
    name = _v1()["runs"][0]["name"]
    run = local / "rf-sintering" / name  # same run, also on the Mac (hand-made folder)
    run.mkdir(parents=True)
    (run / "metadata.json").write_text(json.dumps({"experiment": {"name": name}}))
    c = _client(local)

    doc = c.get("/api/collections").json()
    assert doc["collections"] == [
        {"name": "rf-sintering", "local": True, "drive": True, "offline": True},
    ]
    cards = c.get("/api/experiments", params={"collection": "rf-sintering"}).json()
    by_lib = sorted((it["library"], it["name"]) for it in cards)
    assert ("local", name) in by_lib and ("offline", name) not in by_lib
    assert len(cards) == len(_v1()["runs"]), "deduped by (collection, name)"


def test_no_drive_registered_doc(tmp_path: Path) -> None:
    local = _local(tmp_path)
    (local / "mattmccoy").mkdir()
    doc = _client(local).get("/api/collections").json()
    assert doc["drive_registered"] is False
    assert doc["collections"] == [
        {"name": "mattmccoy", "local": True, "drive": False, "offline": False},
    ]


def test_connected_listing_writes_v2_per_collection(tmp_path: Path) -> None:
    local = _local(tmp_path)
    drive = tmp_path / "Drive"
    drive.mkdir()
    storage.register_drive(local, str(drive))
    for coll, name in (("rf-sintering", "20261110_100000_a"), ("mattmccoy", "20261110_110000_b")):
        d = drive / "FLIR-recordings" / coll / name
        d.mkdir(parents=True)
        (d / "metadata.json").write_text(json.dumps({"experiment": {"name": name}}))
    c = _client(local)
    for coll in ("rf-sintering", "mattmccoy"):
        assert c.get("/api/experiments", params={"collection": coll}).status_code == 200

    idx = _index(local)
    assert idx["schema"] == 2
    assert [(r["collection"], r["name"]) for r in idx["runs"]] == [
        ("mattmccoy", "20261110_110000_b"), ("rf-sintering", "20261110_100000_a"),
    ]


def _connect(c: TestClient) -> None:
    devs = c.get("/api/camera/devices").json()
    r = c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
    assert r.status_code == 200, r.text


def test_record_into_offline_only_collection_creates_local_folder(tmp_path: Path) -> None:
    local = _unplugged(tmp_path)
    with _client(local) as c:
        _connect(c)
        r = c.put("/api/collections/selected", json={"name": "rf-sintering"})
        assert r.status_code == 200, r.text
        r = c.post("/api/recording/start", json={"name": "x"})
        assert r.status_code == 200, r.text
        assert Path(r.json()["experiment_dir"]).parent == local / "rf-sintering"
        assert c.post("/api/recording/stop").status_code == 200
