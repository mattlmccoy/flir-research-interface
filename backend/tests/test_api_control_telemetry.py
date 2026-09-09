"""POST /api/control/telemetry: timeline mark + exports/control.csv while recording."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app


def _client(tmp_path: Path) -> TestClient:
    app = create_app(default_backend="simulated", sim_fps=60.0, viz_fps=30.0,
                     experiments_root=tmp_path, min_free_gb=0.0)
    return TestClient(app)


SAMPLE = {"setpoint_c": 185.0, "measured_c": 182.4, "applied_w": 240.0, "phase": "soak",
          "mode": "auto", "armed": True, "forward_w": 250.0, "reflected_fraction": 0.04,
          "error_c": 2.6, "roi": "circle_medium_small"}


def test_telemetry_is_a_noop_ack_when_not_recording(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        r = c.post("/api/control/telemetry", json=SAMPLE).json()
        assert r["recording"] is False
        assert r["stored"]["setpoint_c"] == 185.0 and "ts" in r["stored"]  # ts auto-filled


def test_control_endpoint_returns_frame_aligned_rf_power(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        c.post("/api/recording/start", json={"name": "rf trace"})
        time.sleep(0.2)
        c.post("/api/control/telemetry", json={**SAMPLE, "forward_w": 100.0})
        time.sleep(0.1)
        c.post("/api/control/telemetry", json={**SAMPLE, "forward_w": 250.0})
        c.post("/api/recording/stop")
        c.post("/api/camera/disconnect")
        runs = [d for d in tmp_path.iterdir() if d.is_dir() and (d / "events.json").exists()]
        s = c.get(f"/api/experiments/{runs[0].name}/control").json()
        assert len(s["t_s"]) == 2 and all(isinstance(t, float) for t in s["t_s"])
        assert s["forward_w"] == [100.0, 250.0]  # RF power over the run, frame-aligned
        assert s["setpoint_c"] == [185.0, 185.0]


def test_control_status_reports_last_telemetry(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        assert c.get("/api/control/status").json()["control_last"] is None
        c.post("/api/control/telemetry", json=SAMPLE)
        st = c.get("/api/control/status").json()
        assert st["control_last"]["setpoint_c"] == 185.0
        assert "rf_link_last_event" in st


def test_telemetry_marks_timeline_and_writes_control_csv_while_recording(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        c.post("/api/recording/start", json={"name": "loop run"})
        time.sleep(0.2)
        assert c.post("/api/control/telemetry", json=SAMPLE).json()["recording"] is True
        assert c.post("/api/control/telemetry",
                      json={**SAMPLE, "measured_c": 184.0}).json()["recording"] is True
        c.post("/api/recording/stop")
        c.post("/api/camera/disconnect")

        # locate the single run folder (created directly under experiments_root=tmp_path)
        runs = [d for d in tmp_path.iterdir() if d.is_dir() and (d / "events.json").exists()]
        assert len(runs) == 1
        run = runs[0]

        # control.csv: header + two rows; frame_id + t_utc lead so power aligns to the frames
        rows = list(csv.reader((run / "exports" / "control.csv").open()))
        assert rows[0][:5] == ["frame_id", "t_utc", "ts", "setpoint_c", "measured_c"]
        assert len(rows) == 3  # header + 2 samples
        cols = {name: i for i, name in enumerate(rows[0])}
        assert rows[1][cols["setpoint_c"]] == "185.0" and rows[1][cols["applied_w"]] == "240.0"
        assert rows[2][cols["measured_c"]] == "184.0"
        assert rows[1][cols["frame_id"]] != ""  # stamped with the frame it landed on

        # timeline event of type "control" was recorded
        events = json.loads((run / "events.json").read_text())
        control_evs = [e for e in events if e.get("type") == "control"]
        assert len(control_evs) == 2 and control_evs[0]["roi"] == "circle_medium_small"
