"""ROIs in force at record time are stored with the recording and their series auto-exported."""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app

ROIS = [
    {"id": 1, "kind": "spot", "x": 10, "y": 10, "name": "centre"},
    {"id": 2, "kind": "rect", "x0": 0, "y0": 0, "x1": 20, "y1": 20, "color": "#ff8ad8"},
    {"id": 3, "kind": "circle", "cx": 30, "cy": 30, "r": 5},
]


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            default_backend="simulated", sim_fps=60.0, experiments_root=tmp_path, min_free_gb=0.0
        )
    )


def test_rois_are_written_to_metadata_and_series_exported_at_stop(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        r = c.post("/api/recording/start", json={"name": "withrois", "rois": ROIS})
        assert r.status_code == 200, r.text
        d = Path(r.json()["experiment_dir"])
        meta = json.loads((d / "metadata.json").read_text())
        assert [x["kind"] for x in meta["rois"]] == ["spot", "rect", "circle"]
        assert meta["rois"][0]["name"] == "centre" and meta["rois"][1]["color"] == "#ff8ad8"
        time.sleep(0.3)
        assert c.post("/api/recording/stop").status_code == 200
        csv_path = d / "exports" / "roi_series.csv"
        assert csv_path.is_file()
        head = [ln for ln in csv_path.read_text().splitlines() if not ln.startswith("#")][0]
        expect = "t_s,frame_id,S1_value,R2_mean,R2_min,R2_max,R2_std,C3_mean,C3_min,C3_max,C3_std"
        assert head == expect
        info = c.get(f"/api/experiments/{d.name}").json()
        assert info["rois"][0]["name"] == "centre"
        c.post("/api/camera/disconnect")


def test_bad_rois_are_rejected_before_anything_is_written(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        r = c.post("/api/recording/start", json={"name": "bad", "rois": [{"id": 1, "kind": "hex"}]})
        assert r.status_code == 400
        assert not any(p.is_dir() for p in tmp_path.iterdir())
        c.post("/api/camera/disconnect")


def test_stop_writes_readme_and_roi_plot(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        d = Path(
            c.post("/api/recording/start", json={"name": "rd", "rois": ROIS}).json()[
                "experiment_dir"
            ]
        )
        time.sleep(0.3)
        assert c.post("/api/recording/stop").status_code == 200
        c.post("/api/camera/disconnect")
        assert "Regions of interest at record time: 3" in (d / "README.txt").read_text()
        assert (d / "exports" / "roi_plot.png").stat().st_size > 1000
