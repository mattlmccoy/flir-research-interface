"""Experiment/playback endpoints."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.api.frames import decode_frame_message
from flir_research_interface.camera.base import Frame
from flir_research_interface.recording.recorder import Recorder


def _exp(root: Path) -> str:
    rec = Recorder(None, experiments_root=root, chunk_frames=4)
    d = rec.start(
        name="pb",
        metadata={},
        camera_info={"backend": "simulated", "ir_format": "TemperatureLinear10mK"},
    )
    for i in range(6):
        rec.submit(
            Frame(
                frame_id=i,
                device_timestamp_ns=i * 33_000_000,
                host_timestamp_ns=i,
                pixel_format="Mono16",
                ir_format="TemperatureLinear10mK",
                counts=np.full((8, 10), 30000 + i, np.uint16),
                incomplete=False,
            )
        )
    rec.stop()
    return d.name


def test_experiment_info_timeline_and_frames(tmp_path: Path) -> None:
    name = _exp(tmp_path)
    app = create_app(experiments_root=tmp_path)
    with TestClient(app) as c:
        info = c.get(f"/api/experiments/{name}").json()
        assert info["n_frames"] == 6 and info["complete"] is True
        tl = c.get(f"/api/experiments/{name}/timeline").json()
        assert len(tl["t_s"]) == 6 and tl["frame_id"][2] == 2
        r = c.get(f"/api/experiments/{name}/frames/4")
        assert r.status_code == 200 and r.headers["content-type"] == "application/octet-stream"
        header, data = decode_frame_message(r.content)
        assert header["frame_id"] == 4 and header["index"] == 4 and header["n_frames"] == 6
        assert header["t_s"] == 4 * 0.033 and int(data[0, 0]) == 30004
        assert c.get(f"/api/experiments/{name}/frames/6").status_code == 404
        assert c.get("/api/experiments/does-not-exist").status_code == 404
        assert c.get("/api/experiments/../etc").status_code in (400, 404)
