"""Milestone 8: operator event marks during recording and post-hoc metadata edits."""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.camera.base import Frame
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.recording.recorder import Recorder


def _frame(i: int) -> Frame:
    return Frame(
        frame_id=100 + i,
        device_timestamp_ns=1_000_000_000 + i * 100_000_000,
        host_timestamp_ns=5_000_000_000 + i * 100_000_000,
        pixel_format="Mono16",
        ir_format="TemperatureLinear10mK",
        counts=np.full((6, 8), 29815, dtype=np.uint16),
        incomplete=False,
    )


def test_note_event_stamps_the_last_frame_id(tmp_path: Path) -> None:
    rec = Recorder(None, experiments_root=tmp_path, chunk_frames=4)
    d = rec.start(name="ev", metadata={}, camera_info={"ir_format": "TemperatureLinear10mK"})
    rec.note_event("annotation", {"name": "RF ON"})  # before any frame: no frame_id
    for i in range(3):
        rec.submit(_frame(i))
    rec.note_event("annotation", {"name": "RF OFF", "note": "arc"})
    rec.stop()
    events = json.loads((d / "events.json").read_text())
    marks = [e for e in events if e["type"] == "annotation"]
    assert marks[0]["name"] == "RF ON" and "frame_id" not in marks[0]
    assert marks[1]["name"] == "RF OFF" and marks[1]["frame_id"] == 102
    assert marks[1]["note"] == "arc" and "t_utc" in marks[1]


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        default_backend="simulated", sim_fps=60.0, experiments_root=tmp_path, min_free_gb=0.0
    )
    return TestClient(app)


def test_event_endpoint_requires_recording_and_lands_in_events_json(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        assert c.post("/api/recording/event", json={"name": "RF ON"}).status_code == 409
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        assert c.post("/api/recording/start", json={"name": "marks"}).status_code == 200
        time.sleep(0.2)
        r = c.post("/api/recording/event", json={"name": "RF ON", "note": "300 W"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["type"] == "annotation" and body["name"] == "RF ON"
        assert isinstance(body.get("frame_id"), int)
        assert c.post("/api/recording/event", json={"name": ""}).status_code == 400
        exp_dir = Path(c.get("/api/recording/status").json()["experiment_dir"])
        c.post("/api/recording/stop")
        events = json.loads((exp_dir / "events.json").read_text())
        mark = next(e for e in events if e["type"] == "annotation")
        assert mark["name"] == "RF ON" and mark["note"] == "300 W"
        c.post("/api/camera/disconnect")


def test_metadata_patch_merges_experiment_keys_and_logs_edits(tmp_path: Path) -> None:
    rec = Recorder(None, experiments_root=tmp_path, chunk_frames=4)
    d = rec.start(
        name="meta",
        metadata={"material": "PA12", "rf_forward_power_w": 300},
        camera_info={"ir_format": "TemperatureLinear10mK"},
    )
    rec.submit(_frame(0))
    rec.stop()
    app = create_app(default_backend="simulated", experiments_root=tmp_path)
    with TestClient(app) as c:
        r = c.patch(
            f"/api/experiments/{d.name}/metadata",
            json={"experiment": {"rf_forward_power_w": 400, "notes": "re-measured"}},
        )
        assert r.status_code == 200, r.text
        exp = r.json()["experiment"]
        assert exp["material"] == "PA12" and exp["rf_forward_power_w"] == 400
        assert exp["notes"] == "re-measured"
        meta = json.loads((d / "metadata.json").read_text())
        assert meta["experiment"]["rf_forward_power_w"] == 400
        assert meta["camera"]["ir_format"] == "TemperatureLinear10mK"  # untouched
        assert len(meta["edits"]) == 1
        assert meta["edits"][0]["keys"] == ["notes", "rf_forward_power_w"]
        assert "t_utc" in meta["edits"][0]
        # a null value removes a key
        r2 = c.patch(f"/api/experiments/{d.name}/metadata", json={"experiment": {"notes": None}})
        assert "notes" not in r2.json()["experiment"]
        bad = c.patch(f"/api/experiments/{d.name}/metadata", json={"experiment": 5})
        assert bad.status_code == 400
        assert c.patch("/api/experiments/nope/metadata", json={"experiment": {}}).status_code == 404
        assert ExperimentReader(d).metadata["experiment"]["rf_forward_power_w"] == 400
        # the reserved name key cannot be overwritten (it names the directory)
        r3 = c.patch(f"/api/experiments/{d.name}/metadata", json={"experiment": {"name": "x"}})
        assert r3.status_code == 400
