"""M11: arm a recording; the operator starts and stops it from the trigger, with a pre-trigger
buffer, and stamps trigger events. Simulated camera, 'after' start and 'frames' end."""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.camera.base import Frame
from flir_research_interface.recording.arm import watched_value


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            default_backend="simulated", sim_fps=60.0, experiments_root=tmp_path, min_free_gb=0.0
        )
    )


def _wait(c: TestClient, pred, timeout: float = 10.0):  # type: ignore[no-untyped-def]
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        st = c.get("/api/recording/status").json()
        if pred(st):
            return st
        time.sleep(0.05)
    raise AssertionError(f"timeout; last status {st}")


def test_watched_value_evaluates_the_roi_stat_on_a_frame() -> None:
    counts = np.full((4, 4), 29815, np.uint16)  # 25.00 °C
    counts[1, 1] = 29815 + 1000  # 35 °C
    f = Frame(
        frame_id=1,
        device_timestamp_ns=0,
        host_timestamp_ns=0,
        pixel_format="Mono16",
        ir_format="TemperatureLinear10mK",
        counts=counts,
        incomplete=False,
    )
    rect = {"id": 1, "kind": "rect", "x0": 0, "y0": 0, "x1": 4, "y1": 4}
    assert watched_value(f, rect, "max") == 35.0
    assert watched_value(f, rect, "min") == 25.0
    assert watched_value(f, {"id": 2, "kind": "spot", "x": 1, "y": 1}, "value") == 35.0
    assert (
        watched_value(f, {"id": 3, "kind": "rect", "x0": 9, "y0": 9, "x1": 10, "y1": 10}, "mean")
        is None
    )


def test_arm_then_auto_start_and_auto_stop(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        body = {
            "name": "armed",
            "metadata": {"operator": "t"},
            "trigger": {
                "start": {"kind": "after", "after_s": 0.3},
                "end": {"kind": "frames", "frames": 30},
                "pretrigger_s": 0.2,
            },
        }
        r = c.post("/api/recording/arm", json=body)
        assert r.status_code == 200, r.text
        assert r.json()["state"] == "armed"
        st = c.get("/api/recording/status").json()
        assert st["state"] == "armed" and st["armed"]["trigger"]["start"]["kind"] == "after"
        assert (
            c.post("/api/recording/start", json={"name": "x"}).status_code == 409
        )  # armed: no manual start
        st = _wait(c, lambda s: s["state"] == "recording")
        d = Path(st["experiment_dir"])
        st = _wait(c, lambda s: s["state"] == "idle" and "armed" not in s)
        man = json.loads((d / "manifest.json").read_text())
        assert man["frames_written"] >= 30 + 5, (
            man
        )  # 30 triggered frames + ~0.2 s pre-trigger at 60 fps
        ev = json.loads((d / "events.json").read_text())
        kinds = [e["type"] for e in ev]
        assert "trigger" in kinds and "trigger_end" in kinds
        trig = next(e for e in ev if e["type"] == "trigger")
        assert trig["start"]["kind"] == "after" and trig["pretrigger_frames"] >= 5
        assert next(e for e in ev if e["type"] == "trigger_end")["reason"] == "frames"
        c.post("/api/camera/disconnect")


def test_disarm_and_refusals(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        assert (
            c.post("/api/recording/arm", json={"name": "n", "trigger": {}}).status_code == 409
        )  # no camera
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        bad = {"name": "n", "trigger": {"start": {"kind": "threshold"}, "end": {"kind": "manual"}}}
        assert c.post("/api/recording/arm", json=bad).status_code == 400
        ok = {"name": "n", "trigger": {"start": {"kind": "manual"}, "end": {"kind": "manual"}}}
        assert c.post("/api/recording/arm", json=ok).status_code == 200
        assert c.post("/api/recording/arm", json=ok).status_code == 409  # already armed
        assert c.post("/api/recording/disarm").status_code == 200
        assert c.get("/api/recording/status").json()["state"] == "idle"
        assert not any(p.is_dir() for p in tmp_path.iterdir())  # disarm before start writes nothing
        assert c.post("/api/recording/disarm").status_code == 409
        c.post("/api/camera/disconnect")
