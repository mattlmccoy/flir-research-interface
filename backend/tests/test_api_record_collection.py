"""Recording and arming into the selected collection; Record/Arm block; picker lock (Task 5).

Simulated camera; the ``.collection.json`` written directly in the last test is a hand-made shape
matching ``save_selection`` (collections.py), used to simulate a bypass of the picker lock.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from collection_helpers import select_collection
from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.collections import SELECTION_FILE

PICK = "pick a collection before recording"
LOCKED = "the collection can't change while a recording or armed trigger is active"
ARM_BODY: dict[str, Any] = {
    "name": "armed",
    "metadata": {"operator": "t"},
    "trigger": {
        "start": {"kind": "after", "after_s": 0.3},
        "end": {"kind": "frames", "frames": 30},
        "pretrigger_s": 0.2,
    },
}
MANUAL_ARM: dict[str, Any] = {
    "name": "armed",
    "trigger": {"start": {"kind": "manual"}, "end": {"kind": "manual"}},
}


def _client(root: Path) -> TestClient:
    return TestClient(
        create_app(
            default_backend="simulated", sim_fps=60.0, experiments_root=root, min_free_gb=0.0
        )
    )


def _connect(c: TestClient) -> None:
    devs = c.get("/api/camera/devices").json()
    r = c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
    assert r.status_code == 200, r.text


def _wait(c: TestClient, pred, timeout: float = 10.0):  # type: ignore[no-untyped-def]
    t0 = time.monotonic()
    st: dict[str, Any] = {}
    while time.monotonic() - t0 < timeout:
        st = c.get("/api/recording/status").json()
        if pred(st):
            return st
        time.sleep(0.05)
    raise AssertionError(f"timeout; last status {st}")


def test_record_refuses_without_collection(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    with _client(root) as c:
        _connect(c)
        for _ in range(2):  # nothing selected, then Unsorted ("")
            r = c.post("/api/recording/start", json={"name": "x"})
            assert r.status_code == 409 and r.json()["detail"] == PICK
            r = c.post("/api/recording/arm", json=MANUAL_ARM)
            assert r.status_code == 409 and r.json()["detail"] == PICK
            assert c.put("/api/collections/selected", json={"name": ""}).status_code == 200
        assert c.get("/api/recording/status").json()["state"] == "idle"


def test_record_writes_into_collection(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    with _client(root) as c:
        _connect(c)
        select_collection(c, "rf-sintering")
        (root / "rf-sintering").rmdir()  # e.g. it exists only on the unplugged drive (R1)
        r = c.post("/api/recording/start", json={"name": "x"})
        assert r.status_code == 200, r.text
        assert Path(r.json()["experiment_dir"]).parent == root / "rf-sintering"
        assert c.get("/api/recording/status").json()["collection"] == "rf-sintering"
        assert c.post("/api/recording/stop").status_code == 200


def test_picker_locked_while_armed_and_recording(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    with _client(root) as c:
        _connect(c)
        select_collection(c, "a")
        select_collection(c, "b")
        assert c.post("/api/recording/start", json={"name": "x"}).status_code == 200
        r = c.put("/api/collections/selected", json={"name": "a"})
        assert r.status_code == 409 and r.json()["detail"] == LOCKED
        assert c.post("/api/recording/stop").status_code == 200
        assert c.put("/api/collections/selected", json={"name": "a"}).status_code == 200

        assert c.post("/api/recording/arm", json=MANUAL_ARM).status_code == 200
        assert c.get("/api/recording/status").json()["collection"] == "a"
        r = c.put("/api/collections/selected", json={"name": "b"})
        assert r.status_code == 409 and r.json()["detail"] == LOCKED
        assert c.post("/api/recording/disarm").status_code == 200
        assert c.put("/api/collections/selected", json={"name": "b"}).status_code == 200


def test_armed_start_uses_arm_time_collection(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    with _client(root) as c:
        _connect(c)
        select_collection(c, "other")
        select_collection(c, "mattmccoy")
        assert c.post("/api/recording/arm", json=ARM_BODY).status_code == 200
        (root / SELECTION_FILE).write_text(json.dumps({"selected": "other"}))  # bypass the lock
        st = _wait(c, lambda s: s["state"] == "recording")
        assert Path(st["experiment_dir"]).parent == root / "mattmccoy"
        _wait(c, lambda s: s["state"] == "idle")


def test_recording_stamps_user_and_user_switch_is_locked(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    with _client(root) as c:
        _connect(c)
        assert c.post("/api/users", json={"name": "Matt McCoy"}).status_code == 200
        assert c.post("/api/users", json={"name": "Ana"}).status_code == 200
        assert c.put("/api/users/current", json={"id": "mattmccoy"}).status_code == 200
        r = c.post("/api/recording/start", json={"name": "x"})
        assert r.status_code == 200, r.text
        run = Path(r.json()["experiment_dir"])
        assert run.parent == root / "mattmccoy"
        r = c.put("/api/users/current", json={"id": "ana"})
        assert r.status_code == 409
        assert c.post("/api/recording/stop").status_code == 200
        _wait(c, lambda s: s["state"] == "idle")
        meta = json.loads((run / "metadata.json").read_text())
        assert meta["user"] == {"id": "mattmccoy", "name": "Matt McCoy"}
