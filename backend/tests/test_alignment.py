"""Visible↔IR alignment stored on the operator and stamped into recording metadata."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app

ALIGN = {
    "pairs": [{"ir": [0.1, 0.1], "visible": [0.2, 0.2]}] * 4,
    "H": [[0.9, 0.0, 0.05], [0.0, 0.9, 0.05], [0.0, 0.0, 1.0]],
    "rmsPx": 1.2,
    "note": "sample plane at 0.45 m",
}


def test_alignment_roundtrip_and_validation(tmp_path: Path) -> None:
    app = create_app(default_backend="simulated", experiments_root=tmp_path, min_free_gb=0.0)
    with TestClient(app) as c:
        assert c.get("/api/calibration/visible").status_code == 404
        r = c.put("/api/calibration/visible", json=ALIGN)
        assert r.status_code == 200, r.text
        body = c.get("/api/calibration/visible").json()
        assert body["H"] == ALIGN["H"] and body["note"] == ALIGN["note"]
        assert "saved_utc" in body
        # stored next to the experiments root (shared by every browser), not inside it
        path = tmp_path.parent / "calibration" / "visible_alignment.json"
        stored = json.loads(path.read_text())
        assert stored["H"] == ALIGN["H"]
        assert c.put("/api/calibration/visible", json={"H": "nope"}).status_code == 400
        assert c.put("/api/calibration/visible", json={"H": [[1, 2], [3, 4]]}).status_code == 400


def test_recording_metadata_carries_the_alignment(tmp_path: Path) -> None:
    app = create_app(
        default_backend="simulated", sim_fps=60.0, experiments_root=tmp_path, min_free_gb=0.0
    )
    with TestClient(app) as c:
        c.put("/api/calibration/visible", json=ALIGN)
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        d = c.post("/api/recording/start", json={"name": "aligned"}).json()["experiment_dir"]
        c.post("/api/recording/stop")
        meta = json.loads((Path(d) / "metadata.json").read_text())
        assert meta["visible_alignment"]["H"] == ALIGN["H"]
        assert meta["visible_alignment"]["note"] == ALIGN["note"]
        c.post("/api/camera/disconnect")
