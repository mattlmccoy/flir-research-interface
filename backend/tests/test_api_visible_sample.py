"""Visible-sample analysis wired into the app: post-stop chain, derived job, experiment info.

The analysis itself is covered by test_visible_sample_run.py; here ``analyse_visible_sample`` and
the thermal video render are stubbed (the wiring is what is under test, and the runs are simulated
recordings with no visible video). The stubs are patched at the module the app imports them from
inside its step functions, so the patch is seen when the step runs.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from flir_research_interface.analysis import thermal_video, visible_sample_run
from flir_research_interface.api.app import create_app

SUMMARY = {"status": "ok", "reason": None, "events": [], "files": ["visible_sample.json"]}


class _Calls:
    """What the stubs saw, in order: ``("visible", run, closeup)`` and ``("video", run)``."""

    def __init__(self) -> None:
        self.log: list[tuple[Any, ...]] = []

    def named(self, kind: str) -> list[tuple[Any, ...]]:
        return [c for c in self.log if c[0] == kind]


@pytest.fixture()
def calls(monkeypatch: pytest.MonkeyPatch) -> _Calls:
    seen = _Calls()

    def fake_analyse(reader: Any, ffmpeg: Any = None, ffprobe: Any = None,
                     closeup: bool = True) -> dict[str, Any]:
        seen.log.append(("visible", reader.path.name, closeup))
        return dict(SUMMARY)

    def fake_render(reader: Any, **_kw: Any) -> None:
        seen.log.append(("video", reader.path.name))

    monkeypatch.setattr(visible_sample_run, "analyse_visible_sample", fake_analyse)
    monkeypatch.setattr(thermal_video, "render_thermal_video", fake_render)
    return seen


def _app(tmp_path: Path) -> FastAPI:
    return create_app(
        default_backend="simulated", sim_fps=60.0, experiments_root=tmp_path, min_free_gb=0.0
    )


def _wait_for(cond: Callable[[], bool], what: str, timeout: float = 15.0) -> None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


def _wait_derived(c: TestClient, name: str, timeout: float = 30.0) -> dict[str, Any]:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        job: dict[str, Any] = c.get(f"/api/experiments/{name}/export/derived/status").json()
        if job["state"] in ("done", "error"):
            return job
        time.sleep(0.05)
    raise AssertionError("derived job did not finish in time")


def _record(c: TestClient, calls: _Calls) -> str:
    """Record a short simulated run, stop it, and wait for the post-stop chain to finish."""
    devs = c.get("/api/camera/devices").json()
    c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
    r = c.post("/api/recording/start", json={"name": "run"})
    assert r.status_code == 200, r.text
    name = Path(r.json()["experiment_dir"]).name
    time.sleep(0.3)
    assert c.post("/api/recording/stop").status_code == 200
    # the thermal video is the last step of the chain, so its call means the chain is over
    _wait_for(lambda: bool(calls.named("video")), "the post-stop chain")
    return name


def test_experiment_info_includes_visible_sample(tmp_path: Path, calls: _Calls) -> None:
    with TestClient(_app(tmp_path)) as c:
        name = _record(c, calls)
        summary = {"status": "ok", "reason": None, "events": [{"t_start_s": 4.0}]}
        (tmp_path / name / "exports" / "visible_sample.json").write_text(json.dumps(summary))
        info = c.get(f"/api/experiments/{name}").json()
        assert info["visible_sample"] == summary
        c.post("/api/camera/disconnect")


def test_experiment_info_visible_sample_absent(tmp_path: Path, calls: _Calls) -> None:
    with TestClient(_app(tmp_path)) as c:
        name = _record(c, calls)
        assert not (tmp_path / name / "exports" / "visible_sample.json").exists()
        r = c.get(f"/api/experiments/{name}")
        assert r.status_code == 200
        assert r.json()["visible_sample"] is None
        c.post("/api/camera/disconnect")


@pytest.mark.parametrize("text", ["{not json", "", "[1, 2]"])
def test_experiment_info_visible_sample_invalid_is_none(
    tmp_path: Path, calls: _Calls, text: str
) -> None:
    """A truncated, empty or non-object file must never break the endpoint."""
    with TestClient(_app(tmp_path)) as c:
        name = _record(c, calls)
        (tmp_path / name / "exports" / "visible_sample.json").write_text(text)
        r = c.get(f"/api/experiments/{name}")
        assert r.status_code == 200
        assert r.json()["visible_sample"] is None
        c.post("/api/camera/disconnect")


def test_derived_job_runs_visible_step(
    tmp_path: Path, calls: _Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path)
    steps: list[str] = []
    with TestClient(app) as c:
        name = _record(c, calls)
        calls.log.clear()  # the post-stop chain already ran the analysis once
        real = visible_sample_run.analyse_visible_sample

        def spy(reader: Any, **kw: Any) -> dict[str, Any]:
            steps.append(app.state.derived_jobs[name]["step"])  # which step called it
            return real(reader, **kw)  # type: ignore[no-any-return]

        monkeypatch.setattr(visible_sample_run, "analyse_visible_sample", spy)
        r = c.post(f"/api/experiments/{name}/export/derived?video=false")
        assert r.status_code == 200 and r.json()["state"] == "running"
        job = _wait_derived(c, name)
        assert job["state"] == "done", job
        assert calls.named("visible") == [("visible", name, True)]  # once, close-ups on
        assert steps == ["visible sample"]
        assert calls.named("video") == []  # video=false still skips the thermal video
        c.post("/api/camera/disconnect")


def test_derived_visible_failure_does_not_fail_the_job(
    tmp_path: Path, calls: _Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    with TestClient(_app(tmp_path)) as c:
        name = _record(c, calls)

        def boom(reader: Any, **_kw: Any) -> dict[str, Any]:
            calls.log.append(("boom", reader.path.name))
            raise RuntimeError("ffmpeg exploded")

        monkeypatch.setattr(visible_sample_run, "analyse_visible_sample", boom)
        c.post(f"/api/experiments/{name}/export/derived?video=false")
        job = _wait_derived(c, name)
        assert job["state"] == "done", job
        assert calls.named("boom") == [("boom", name)]  # it ran, and the job survived it
        c.post("/api/camera/disconnect")


def test_post_stop_runs_visible_before_the_thermal_video(tmp_path: Path, calls: _Calls) -> None:
    with TestClient(_app(tmp_path)) as c:
        name = _record(c, calls)
        assert [k[0] for k in calls.log] == ["visible", "video"]
        assert calls.log[0] == ("visible", name, True)
        c.post("/api/camera/disconnect")


def test_post_stop_visible_failure_does_not_break_chain(
    tmp_path: Path, calls: _Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(reader: Any, **_kw: Any) -> dict[str, Any]:
        calls.log.append(("boom", reader.path.name))
        raise RuntimeError("ffmpeg exploded")

    monkeypatch.setattr(visible_sample_run, "analyse_visible_sample", boom)
    with TestClient(_app(tmp_path)) as c:
        name = _record(c, calls)  # waits for the video step: it ran despite the failure
        assert [k[0] for k in calls.log] == ["boom", "video"]
        assert calls.named("video") == [("video", name)]
        c.post("/api/camera/disconnect")


@pytest.mark.parametrize(
    ("summary", "needle"),
    [
        ({"status": "failed", "reason": "OSError: disk full", "plot_error": None}, "disk full"),
        ({"status": "ok", "reason": None, "plot_error": "ValueError: bad axes"}, "bad axes"),
    ],
)
def test_failed_summary_or_plot_error_is_logged_as_a_warning(
    tmp_path: Path, calls: _Calls, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture, summary: dict[str, Any], needle: str,
) -> None:
    monkeypatch.setattr(
        visible_sample_run, "analyse_visible_sample", lambda reader, **kw: summary
    )
    with caplog.at_level(logging.WARNING, logger="flir_research_interface.api.app"):
        with TestClient(_app(tmp_path)) as c:
            name = _record(c, calls)
            c.post("/api/camera/disconnect")
    warned = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any(name in m and needle in m for m in warned), warned


def test_ok_summary_logs_no_warning(
    tmp_path: Path, calls: _Calls, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="flir_research_interface.api.app"):
        with TestClient(_app(tmp_path)) as c:
            _record(c, calls)
            c.post("/api/camera/disconnect")
    assert not [r for r in caplog.records if "visible sample" in r.getMessage()]


def test_real_analysis_of_a_run_without_visible_video_is_skipped_and_exposed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end with the analysis not stubbed: the post-stop step writes the JSON and the run's
    info shows it. (Only the thermal video, which ends the chain, is stubbed to keep it short.)"""
    chain_done: list[str] = []
    monkeypatch.setattr(
        thermal_video, "render_thermal_video", lambda reader, **kw: chain_done.append("video")
    )
    with TestClient(_app(tmp_path)) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        started = c.post("/api/recording/start", json={"name": "run"}).json()
        name = Path(started["experiment_dir"]).name
        time.sleep(0.3)
        c.post("/api/recording/stop")
        _wait_for(lambda: bool(chain_done), "the post-stop chain")
        path = tmp_path / name / "exports" / "visible_sample.json"
        on_disk = json.loads(path.read_text())
        assert on_disk["status"] == "skipped" and on_disk["reason"]
        assert c.get(f"/api/experiments/{name}").json()["visible_sample"] == on_disk
        c.post("/api/camera/disconnect")
