"""RF link: external RF on/off events, unified into the armed-recording trigger.

Recording start/stop is driven by an "on RF signal" armed trigger (not a separate auto-start
setting): an RF-on edge starts a recording only when such a trigger is armed; an RF-off edge stops
a recording armed to end on RF; and either edge marks the timeline while a recording runs. A
manual/operator recording is never stopped by an RF-off edge.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(default_backend="simulated", sim_fps=60.0,
                                 experiments_root=tmp_path, min_free_gb=0.0))


def _wait(c: TestClient, pred, timeout: float = 10.0):  # type: ignore[no-untyped-def]
    t0 = time.monotonic()
    st: dict = {}
    while time.monotonic() - t0 < timeout:
        st = c.get("/api/recording/status").json()
        if pred(st):
            return st
        time.sleep(0.05)
    raise AssertionError(f"timeout; last status {st}")


def _connect(c: TestClient) -> None:
    devs = c.get("/api/camera/devices").json()
    c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})


def _arm_rf(c: TestClient) -> None:
    body = {"name": "rf run", "trigger": {"start": {"kind": "rf"}, "end": {"kind": "rf"},
                                          "pretrigger_s": 0.1}}
    assert c.post("/api/recording/arm", json=body).json()["state"] == "armed"


def test_settings_reports_only_the_last_event_now(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        body = c.get("/api/rf-link/settings").json()
        assert body == {"last_event": None}  # start/stop policy moved to the recording trigger


def test_rf_on_starts_an_armed_rf_trigger_and_marks_the_timeline(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        _connect(c)
        _arm_rf(c)
        r = c.post("/api/rf-link/event", json={"state": "on", "forward_w": 300.0})
        assert r.status_code == 200 and r.json()["triggered"] == "start"
        st = _wait(c, lambda s: s["state"] == "recording")
        d = Path(st["experiment_dir"])
        # RF-off stops it (armed end == rf)
        r = c.post("/api/rf-link/event", json={"state": "off", "reason": "operator"})
        assert r.json()["triggered"] == "stop"
        _wait(c, lambda s: s["state"] == "idle" and "armed" not in s)
        ev = json.loads((d / "events.json").read_text())
        kinds = [e["type"] for e in ev]
        assert "trigger" in kinds  # armed start recorded
        trig = next(e for e in ev if e["type"] == "trigger")
        assert trig["start"]["kind"] == "rf" and trig["rf"]["forward_w"] == 300.0
        names = [e.get("name") for e in ev if e["type"] == "annotation"]
        assert "RF ON" in names  # timeline marked while recording
        c.post("/api/camera/disconnect")


def test_rf_on_does_nothing_when_no_rf_trigger_is_armed(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        _connect(c)
        r = c.post("/api/rf-link/event", json={"state": "on", "forward_w": 300.0})
        assert r.status_code == 200 and r.json()["triggered"] == ""
        assert r.json()["recording"] is False  # no standalone auto-start any more
        # but the event is still recorded for display
        assert c.get("/api/rf-link/settings").json()["last_event"]["state"] == "on"
        c.post("/api/camera/disconnect")


def test_rf_off_never_stops_a_manual_recording(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        _connect(c)
        assert c.post("/api/recording/start", json={"name": "manual"}).status_code == 200
        time.sleep(0.2)
        r = c.post("/api/rf-link/event", json={"state": "off", "reason": "operator"})
        assert r.json()["triggered"] == ""  # not an rf-armed recording → not stopped
        assert c.get("/api/recording/status").json()["state"] == "recording"
        c.post("/api/recording/stop")
        c.post("/api/camera/disconnect")


def test_settings_reports_last_rf_link_event(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        assert c.get("/api/rf-link/settings").json()["last_event"] is None
        c.post("/api/rf-link/event", json={"state": "on", "forward_w": 300.0})
        last = c.get("/api/rf-link/settings").json()["last_event"]
        assert last is not None and last["state"] == "on" and "ts" in last
