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
