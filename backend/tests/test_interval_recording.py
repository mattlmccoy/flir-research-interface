"""Periodic (time-lapse) recording: keep every Nth frame; the skipped frames are intentional,
counted separately, and never make the recording 'incomplete'."""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.camera.base import Frame
from flir_research_interface.recording.recorder import Recorder


def _frame(i: int) -> Frame:
    return Frame(
        frame_id=i,
        device_timestamp_ns=i * 33_333_333,
        host_timestamp_ns=i,
        pixel_format="Mono16",
        ir_format="TemperatureLinear10mK",
        counts=np.full((4, 4), 30000 + i, np.uint16),
        incomplete=False,
    )


def test_recorder_keeps_every_nth_frame(tmp_path: Path) -> None:
    rec = Recorder(None, experiments_root=tmp_path, chunk_frames=4, min_free_gb=0.0, every_nth=3)
    d = rec.start(name="lapse", metadata={}, camera_info={"ir_format": "TemperatureLinear10mK"})
    for i in range(10):
        rec.submit(_frame(i))
    man = rec.stop()
    assert man["frames_written"] == 4 and man["frames_received"] == 10  # ids 0,3,6,9
    assert man["frames_skipped_interval"] == 6 and man["complete"] is True
    meta = json.loads((d / "metadata.json").read_text())
    assert meta["store"]["every_nth"] == 3


def test_api_start_accepts_every_nth(tmp_path: Path) -> None:
    app = create_app(
        default_backend="simulated", sim_fps=60.0, experiments_root=tmp_path, min_free_gb=0.0
    )
    with TestClient(app) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        r = c.post(
            "/api/recording/start", json={"name": "lapse", "every_nth": 10, "nuc_hold": False}
        )
        assert r.status_code == 200, r.text
        time.sleep(0.5)
        st = c.get("/api/recording/status").json()
        assert st["every_nth"] == 10 and st["frames_received"] > st["frames_written"] * 5
        c.post("/api/recording/stop")
        assert (
            c.post("/api/recording/start", json={"name": "bad", "every_nth": 0}).status_code == 422
        )
        c.post("/api/camera/disconnect")
