"""A slow finalize must only touch the run it began with (2026-09-30 incident).

Run 20260930_142445 was ended with three Disconnect clicks. The first click's finalize spent ~7 min
in the post-stop exports; the other clicks released the camera, the operator reconnected and
started run 143846, and when the stale finalize finally returned it stopped the NEW run's visible
recorder and disconnected the NEW camera session, leaving the new thermal recorder with no frames.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from flir_research_interface.analysis import run_summary
from flir_research_interface.api.app import create_app


class FakeVisible:
    """Stands in for VisibleRecorder: records whether it was stopped."""

    def __init__(self) -> None:
        self.stopped = False

    def start(self, exp_dir: Path) -> dict[str, Any]:
        return {"state": "recording"}

    def stop(self) -> dict[str, Any]:
        self.stopped = True
        return {"state": "stopped", "returncode": 0}

    def stats(self) -> dict[str, Any]:
        return {"state": "stopped" if self.stopped else "recording"}


@dataclass
class StaleFinalizeScenario:
    client: TestClient
    visibles: list[FakeVisible]
    stale_response: dict[str, Any] = field(default_factory=dict)


def _connect(c: TestClient) -> None:
    devs = c.get("/api/camera/devices").json()
    r = c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
    assert r.status_code == 200, r.text


@pytest.fixture
def stale_finalize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[StaleFinalizeScenario]:
    """Run A is disconnected with a slow export; run B starts before that export returns."""
    entered, release = threading.Event(), threading.Event()
    real_summary = run_summary.write_run_summary

    def slow_summary(reader: Any) -> dict[str, Any]:
        if not entered.is_set():  # only run A's export is slow
            entered.set()
            assert release.wait(20), "test never released the slow export"
        return real_summary(reader)

    monkeypatch.setattr(run_summary, "write_run_summary", slow_summary)
    visibles: list[FakeVisible] = []

    def factory() -> FakeVisible:
        visibles.append(FakeVisible())
        return visibles[-1]

    app = create_app(
        default_backend="simulated",
        sim_fps=60.0,
        experiments_root=tmp_path,
        min_free_gb=0.0,
        visible_factory=factory,
    )
    with TestClient(app) as c:
        scenario = StaleFinalizeScenario(client=c, visibles=visibles)
        _connect(c)
        r = c.post("/api/recording/start", json={"name": "A", "visible": True})
        assert r.status_code == 200, r.text
        time.sleep(0.3)

        def _stale_disconnect() -> None:
            scenario.stale_response.update(c.post("/api/camera/disconnect").json())

        stale = threading.Thread(target=_stale_disconnect)
        stale.start()
        assert entered.wait(20), "run A's finalize never reached the export"
        # the operator clicks Disconnect again, reconnects, and starts run B
        assert c.post("/api/camera/disconnect").status_code == 200
        _connect(c)
        r = c.post("/api/recording/start", json={"name": "B", "visible": True})
        assert r.status_code == 200, r.text
        release.set()
        stale.join(20)
        assert not stale.is_alive()
        yield scenario
        c.post("/api/recording/stop")
        c.post("/api/camera/disconnect")


def test_stale_finalize_leaves_the_new_runs_visible_recorder_running(
    stale_finalize: StaleFinalizeScenario,
) -> None:
    vis_a, vis_b = stale_finalize.visibles
    assert vis_a.stopped, "run A's own visible recorder must still be stopped"
    assert not vis_b.stopped, "run A's finalize stopped run B's visible recorder"


def test_stale_disconnect_leaves_the_new_camera_session_connected(
    stale_finalize: StaleFinalizeScenario,
) -> None:
    c = stale_finalize.client
    assert c.get("/api/camera/status").json()["state"] == "acquiring"
    assert c.app.state.autoconnect_paused is False  # type: ignore[attr-defined]
    # run B keeps receiving frames (the recorder flushes in batches, so poll rather than sleep once)
    deadline = time.monotonic() + 5.0
    st = c.get("/api/recording/status").json()
    while st["frames_written"] == 0 and time.monotonic() < deadline:
        time.sleep(0.1)
        st = c.get("/api/recording/status").json()
    assert st["state"] == "recording" and st["frames_written"] > 0
