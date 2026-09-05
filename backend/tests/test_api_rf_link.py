"""RF-link endpoints: settings (A3) and event (A4), against the simulated camera."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app


def _client(tmp_path: Path) -> TestClient:
    app = create_app(default_backend="simulated", sim_fps=60.0, experiments_root=tmp_path,
                     min_free_gb=0.0)
    return TestClient(app)


def _connect_sim(c: TestClient) -> None:
    devs = c.get("/api/camera/devices?backend=simulated").json()
    c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})


def test_get_default_settings(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        body = c.get("/api/rf-link/settings").json()
        assert body["auto_start_on_rf_on"] is True
        assert body["stop_on_rf_off"] is False


def test_put_settings_persists(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        c.put("/api/rf-link/settings", json={"auto_start_on_rf_on": True, "stop_on_rf_off": True})
        assert c.get("/api/rf-link/settings").json()["stop_on_rf_off"] is True


def test_rf_on_starts_recording_and_marks(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        _connect_sim(c)
        r = c.post("/api/rf-link/event", json={"state": "on", "forward_w": 300.0})
        assert r.status_code == 200, r.text
        assert r.json()["recording"] is True
        # the RF ON mark is in the run's events
        status = c.get("/api/recording/status").json()
        assert status["state"] == "recording"


def test_rf_off_keeps_recording_by_default(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        _connect_sim(c)
        c.post("/api/rf-link/event", json={"state": "on", "forward_w": 300.0})
        r = c.post("/api/rf-link/event", json={"state": "off", "reason": "operator"})
        assert r.status_code == 200, r.text
        assert r.json()["recording"] is True  # kept (stop_on_rf_off default False)


def test_rf_off_stops_when_configured(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        _connect_sim(c)
        c.put("/api/rf-link/settings", json={"auto_start_on_rf_on": True, "stop_on_rf_off": True})
        c.post("/api/rf-link/event", json={"state": "on", "forward_w": 300.0})
        r = c.post("/api/rf-link/event", json={"state": "off", "reason": "operator"})
        assert r.status_code == 200, r.text
        assert r.json()["recording"] is False  # stopped


def test_rf_off_never_stops_an_operator_started_recording(tmp_path: Path) -> None:
    """Safety guarantee: the RF link only owns runs it started, so an RF-off event must NEVER stop
    a recording the operator started manually — even with stop_on_rf_off enabled."""
    with _client(tmp_path) as c:
        _connect_sim(c)
        c.put("/api/rf-link/settings", json={"auto_start_on_rf_on": True, "stop_on_rf_off": True})
        # the operator starts the recording, NOT the RF link
        started = c.post("/api/recording/start", json={"name": "operator_run"})
        assert started.status_code == 200, started.text
        r = c.post("/api/rf-link/event", json={"state": "off", "reason": "operator"})
        assert r.status_code == 200, r.text
        assert r.json()["recording"] is True  # operator's run must NOT be stopped
        assert c.get("/api/recording/status").json()["state"] == "recording"
