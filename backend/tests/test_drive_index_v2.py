"""Drive index v2: one offline index that keeps every collection's runs (Task 7).

The v1 index is the captured fixture ``drive_index_v1_20261109.json`` (real ``.drive-index.json``,
redacted). v2 entries are derived from it by adding ``collection`` (the v2 shape written by
``storage.remember_drive_runs``). Run folders made with ``mkdir`` + ``metadata.json`` are
hand-made; they cover routing, not run contents.
"""
from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path
from typing import Any

import pytest
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


# -- fix round 1 ---------------------------------------------------------------------------------


def test_concurrent_remembers_keep_both_collections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two scoped listings at once (sync routes run in the threadpool) must not lose an update."""
    local = _local(tmp_path)
    real = storage._atomic_json

    def slow(path: Path, data: dict[str, Any]) -> None:
        time.sleep(0.2)  # widen the read-merge-write window so the threads interleave
        real(path, data)

    monkeypatch.setattr(storage, "_atomic_json", slow)
    base = _v1()["runs"][0]
    threads = [
        threading.Thread(
            target=storage.remember_drive_runs,
            args=(local, [{**base, "name": f"20261110_00000{i}_{c}"}], "FLIR SSD"),
            kwargs={"collection": c},
        )
        for i, c in enumerate(("aa", "bb"))
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert storage.offline_collections(local) == {"aa", "bb"}


def test_v1_index_rewritten_once_to_schema_2(tmp_path: Path) -> None:
    local = _local(tmp_path)
    shutil.copy(FIXTURE, local / storage.INDEX_NAME)
    items = [{**r, "library": "drive", "root": "/x"} for r in _v1()["runs"]]

    storage.remember_drive_runs(local, items, "FLIR SSD", collection=None)
    assert _index(local)["schema"] == 2
    stamp = (local / storage.INDEX_NAME).stat().st_mtime_ns
    time.sleep(0.01)
    storage.remember_drive_runs(local, items, "FLIR SSD", collection=None)
    assert (local / storage.INDEX_NAME).stat().st_mtime_ns == stamp


def test_move_index_entry_rewrites_collection_and_paths(tmp_path: Path) -> None:
    local = _local(tmp_path)
    shutil.copy(FIXTURE, local / storage.INDEX_NAME)  # captured paths: /Volumes/FLIR SSD/...
    run = _v1()["runs"][0]
    drive_root = Path("/Volumes/FLIR SSD/FLIR-recordings")

    storage.move_index_entry(local, run["name"], None, "rf-sintering", drive_root)
    [moved] = storage.offline_runs(local, collection="rf-sintering")
    new_dir = f"{drive_root}/rf-sintering/{run['name']}"
    assert moved["name"] == run["name"]
    assert moved["path"] == new_dir
    assert moved["thermal_preview"]["path"] == f"{new_dir}/exports/thermal_preview.mp4"
    assert run["name"] not in {r["name"] for r in storage.offline_runs(local, collection=None)}
    assert _index(local)["schema"] == 2

    storage.move_index_entry(local, run["name"], "rf-sintering", None, drive_root)
    [back] = [r for r in storage.offline_runs(local, collection=None) if r["name"] == run["name"]]
    assert back["path"] == run["path"]
    # an entry the index does not have: nothing to do, no error
    storage.move_index_entry(local, "20990101_000000_x", None, "aa", drive_root)


def test_drive_move_route_updates_index(tmp_path: Path) -> None:
    local = _local(tmp_path)
    drive = tmp_path / "Drive"
    drive.mkdir()
    storage.register_drive(local, str(drive))
    name = "20261110_100000_a"
    d = drive / "FLIR-recordings" / name
    d.mkdir(parents=True)
    (d / "metadata.json").write_text(json.dumps({"experiment": {"name": name}}))
    with _client(local) as c:
        assert c.get("/api/experiments", params={"collection": ""}).status_code == 200
        assert [r["name"] for r in storage.offline_runs(local, collection=None)] == [name]

        r = c.post(
            f"/api/experiments/{name}/collection?collection=",
            json={"to": "rf-sintering", "library": "drive"},
        )
        assert r.status_code == 200, r.text
    # the target collection was never listed, yet the offline view still has the run
    assert storage.offline_runs(local, collection=None) == []
    [moved] = storage.offline_runs(local, collection="rf-sintering")
    assert moved["name"] == name


def test_unsorted_counts_offline_top_level_runs(tmp_path: Path) -> None:
    local = _local(tmp_path)
    drive = tmp_path / "Drive"
    drive.mkdir()
    storage.register_drive(local, str(drive))  # removes any old index
    shutil.rmtree(drive)  # unplugged
    shutil.copy(FIXTURE, local / storage.INDEX_NAME)  # real v1: every run at the top level
    doc = _client(local).get("/api/collections").json()
    assert doc["unsorted"] == {"local": 0, "drive": 3}
