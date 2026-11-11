"""The single "operator busy" predicate and GET /api/operator/busy.

The API test is the 2026-10-27 case: an operator restart killed post-stop exports that
"recording idle" had missed, so the render_tasks count must keep the operator busy.
"""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from collection_helpers import select_collection
from fastapi.testclient import TestClient

from flir_research_interface.analysis import run_summary
from flir_research_interface.api.app import create_app
from flir_research_interface.busy import BusyInputs, busy_reasons, job_labels

IDLE = BusyInputs(
    recording=False,
    finalizing=False,
    armed=False,
    control_engaged=False,
    running_jobs=(),
    background_tasks=0,
)


def test_idle_is_not_busy() -> None:
    assert busy_reasons(IDLE) == []


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"recording": True}, ["recording"]),
        ({"finalizing": True}, ["finishing a recording"]),
        ({"armed": True}, ["armed trigger"]),
        ({"control_engaged": True}, ["closed-loop control engaged"]),
        ({"running_jobs": ("move a/b",)}, ["move a/b"]),
        ({"background_tasks": 2}, ["2 background task(s)"]),
    ],
)
def test_each_signal_reports(change: dict[str, Any], expected: list[str]) -> None:
    assert busy_reasons(replace(IDLE, **change)) == expected


def test_reasons_come_in_fixed_order() -> None:
    i = BusyInputs(True, True, True, True, ("move a/b", "smart a/b"), 3)
    assert busy_reasons(i) == [
        "recording",
        "finishing a recording",
        "armed trigger",
        "closed-loop control engaged",
        "move a/b",
        "smart a/b",
        "3 background task(s)",
    ]


def test_post_stop_exports_count_as_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = threading.Event()
    real_summary = run_summary.write_run_summary

    def slow_summary(reader: Any) -> dict[str, Any]:
        assert release.wait(20), "test never released the slow export"
        return real_summary(reader)

    monkeypatch.setattr(run_summary, "write_run_summary", slow_summary)
    app = create_app(
        default_backend="simulated", sim_fps=60.0, experiments_root=tmp_path, min_free_gb=0.0
    )
    with TestClient(app) as c:
        devs = c.get("/api/camera/devices").json()
        serial = devs[0]["serial"]
        r = c.post("/api/camera/connect", json={"backend": "simulated", "serial": serial})
        select_collection(c)
        assert r.status_code == 200, r.text
        assert c.get("/api/operator/busy").json() == {"busy": False, "reasons": []}
        assert c.post("/api/recording/start", json={"name": "busy"}).status_code == 200
        time.sleep(0.3)
        assert c.get("/api/operator/busy").json()["reasons"] == ["recording"]
        assert c.post("/api/recording/stop").status_code == 200
        # recording is idle now, but the post-stop exports are still running
        body = c.get("/api/operator/busy").json()
        assert body["busy"] is True
        assert "1 background task(s)" in body["reasons"], body
        release.set()
        deadline = time.monotonic() + 30.0
        while c.get("/api/operator/busy").json()["busy"] and time.monotonic() < deadline:
            time.sleep(0.05)
        assert c.get("/api/operator/busy").json() == {"busy": False, "reasons": []}
        c.post("/api/camera/disconnect")


def test_running_smart_job_is_reported(tmp_path: Path) -> None:
    # smart_jobs keys are (RunRef.key, roi id) with an int roi id (smart_roi_routes.py)
    app = create_app(default_backend="simulated", experiments_root=tmp_path, min_free_gb=0.0)
    with TestClient(app, raise_server_exceptions=False) as c:
        app.state.smart_jobs[("runkey", 3)] = {"state": "running"}
        r = c.get("/api/operator/busy")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["busy"] is True
        assert "smart runkey 3" in body["reasons"]


def test_job_labels_use_real_key_shapes() -> None:
    jobs = {
        "move": {"mattmccoy/r": {"state": "running"}, "old": {"state": "done"}},
        "derived": {"r2": {"state": "running"}},
        "smart": {("mattmccoy/r", 3): {"state": "running"}, ("x", 1): {"state": "error"}},
    }
    assert job_labels(jobs) == ["move mattmccoy/r", "derived r2", "smart mattmccoy/r 3"]
