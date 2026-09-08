"""GET /api/live/roi-temps + PUT /api/live/rois against the simulated camera."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app


def _client(tmp_path: Path) -> TestClient:
    app = create_app(default_backend="simulated", sim_fps=60.0, viz_fps=30.0,
                     experiments_root=tmp_path, min_free_gb=0.0)
    return TestClient(app)


CIRCLE = {"id": 10, "name": "circle_medium_small", "kind": "circle", "cx": 320, "cy": 240, "r": 20}


def test_roi_temps_invalid_before_a_camera_is_acquiring(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        c.put("/api/live/rois", json={"rois": [CIRCLE]})
        p = c.get("/api/live/roi-temps").json()
        assert p["live"] is False and p["stale"] is True
        # the ROI roster is still returned, but invalid — never a healthy-looking zero
        assert p["rois"][0]["name"] == "circle_medium_small"
        assert p["rois"][0]["valid"] is False and p["rois"][0]["mean_c"] is None


def test_roi_temps_reports_live_per_roi_when_acquiring(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        assert c.put("/api/live/rois", json={"rois": [CIRCLE]}).json()["count"] == 1
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        time.sleep(0.3)  # let a frame or two arrive
        p = c.get("/api/live/roi-temps").json()
        assert p["live"] is True and p["stale"] is False
        assert p["frame_id"] is not None and isinstance(p["frame_ts"], str)
        (roi,) = p["rois"]
        assert roi["name"] == "circle_medium_small" and roi["valid"] is True
        assert isinstance(roi["mean_c"], float) and roi["value_c"] is None
        c.post("/api/camera/disconnect")
