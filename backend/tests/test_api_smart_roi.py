"""Smart ROI recorded-run API: compute job, series, per-frame overlay, arm refusal (Task 5)."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from smart_recording import SMART, make_smart_run

from flir_research_interface.api.app import create_app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            default_backend="simulated", sim_fps=60.0, experiments_root=tmp_path, min_free_gb=0.0
        )
    )


def _compute(c: TestClient, name: str, roi_id: int = 7) -> dict[str, Any]:
    r = c.post(f"/api/experiments/{name}/smart-roi/{roi_id}/compute")
    assert r.status_code == 200, r.text
    t0 = time.monotonic()
    while time.monotonic() - t0 < 30.0:
        job: dict[str, Any] = c.get(f"/api/experiments/{name}/smart-roi/{roi_id}/status").json()
        if job["state"] in ("done", "error"):
            return job
        time.sleep(0.05)
    raise AssertionError("smart ROI job did not finish")


def test_api_compute_then_get(tmp_path: Path) -> None:
    name = make_smart_run(tmp_path, n=8).name
    with _client(tmp_path) as c:
        assert c.get(f"/api/experiments/{name}/smart-roi/7").status_code == 404  # not computed
        job = _compute(c, name)
        assert job == {"state": "done", "done": 8, "total": 8, "error": None}
        body = c.get(f"/api/experiments/{name}/smart-roi/7").json()
        assert len(body["t_s"]) == 8 and body["state"][0] == "searching"
        assert body["state"][-1] == "locked" and body["valid"][-1] is True
        assert body["sample"]["mean"][0] is None and body["sample"]["max"][-1] == 150.0
        assert body["sample"]["mean"][-1] > 140.0
        bands = [(g["inner_px"], g["outer_px"]) for g in body["rings"]]
        assert bands == [(0, 5), (5, 10), (10, 25)]
        assert len(body["rings"][0]["mean"]) == 8
        assert body["dims"]["units"] == "px" and body["dims"]["area_px"][0] is None
        assert body["dims"]["area_change_pct"][1] == 0.0  # baseline = first lock
        small = c.get(f"/api/experiments/{name}/smart-roi/7?max_points=3").json()
        assert len(small["t_s"]) <= 3 and len(small["sample"]["max"]) == len(small["t_s"])
        assert c.get(f"/api/experiments/{name}/smart-roi/99").status_code == 404


def test_compute_refuses_non_smart_roi(tmp_path: Path) -> None:
    rois = [SMART, {"id": 2, "kind": "spot", "x": 5, "y": 5}]
    name = make_smart_run(tmp_path, n=2, rois=rois).name
    with _client(tmp_path) as c:
        assert c.post(f"/api/experiments/{name}/smart-roi/2/compute").status_code == 400
        assert c.post(f"/api/experiments/{name}/smart-roi/5/compute").status_code == 404


def test_overlay_window(tmp_path: Path) -> None:
    name = make_smart_run(tmp_path, n=8).name
    with _client(tmp_path) as c:
        assert c.get(f"/api/experiments/{name}/smart-roi/7/overlay?start=0&count=2").status_code \
            == 404
        _compute(c, name)
        ov = c.get(f"/api/experiments/{name}/smart-roi/7/overlay?start=0&count=3").json()
        assert len(ov) == 3
        assert ov[0] == {"id": 7, "state": "searching", "valid": False, "bbox": None,
                         "labels": None}
        assert ov[1]["state"] == "locked" and isinstance(ov[1]["labels"], str)
        assert len(ov[1]["bbox"]) == 4
        tail = c.get(f"/api/experiments/{name}/smart-roi/7/overlay?start=6&count=10").json()
        assert len(tail) == 2  # clipped to the run
        assert c.get(f"/api/experiments/{name}/smart-roi/7/overlay?start=-1&count=2").status_code \
            == 422


def test_arm_rejects_smart_trigger(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        trig = {"start": {"kind": "threshold", "roi": 7, "level_c": 100.0},
                "end": {"kind": "manual"}}
        r = c.post("/api/recording/arm", json={"name": "n", "rois": [SMART], "trigger": trig})
        assert r.status_code == 400 and "smart" in r.json()["detail"]
        end = {"start": {"kind": "manual"},
               "end": {"kind": "threshold", "roi": 7, "level_c": 100.0}}
        r = c.post("/api/recording/arm", json={"name": "n", "rois": [SMART], "trigger": end})
        assert r.status_code == 400
        assert c.get("/api/recording/status").json()["state"] == "idle"
        c.post("/api/camera/disconnect")


def _wait_idle(c: TestClient, timeout_s: float = 60.0) -> None:
    t0 = time.monotonic()
    while c.app.state.render_tasks and time.monotonic() - t0 < timeout_s:  # type: ignore[attr-defined]
        time.sleep(0.05)
    assert not c.app.state.render_tasks  # type: ignore[attr-defined]


def test_post_stop_computes_stored_smart_rois(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with _client(tmp_path) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        r = c.post("/api/recording/start", json={"name": "run", "rois": [SMART]})
        assert r.status_code == 200, r.text
        name = Path(r.json()["experiment_dir"]).name
        time.sleep(0.3)
        assert c.post("/api/recording/stop").status_code == 200
        t0 = time.monotonic()
        while time.monotonic() - t0 < 30.0:
            job = c.get(f"/api/experiments/{name}/smart-roi/7/status").json()
            if job["state"] in ("done", "error"):
                break
            time.sleep(0.05)
        assert job["state"] == "done", job
        assert (tmp_path / name / "smart_roi" / "7.npz").is_file()
        _wait_idle(c)
        failures = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert not failures, [(r.getMessage(), r.exc_text) for r in failures]
        csv_text = (tmp_path / name / "exports" / "roi_series.csv").read_text()
        assert "smart ROI part: thermal edge" in csv_text and "part area px" in csv_text
        assert (tmp_path / name / "exports" / "roi_plot.png").is_file()
        c.post("/api/camera/disconnect")


def _wait_derived(c: TestClient, name: str) -> dict[str, Any]:
    t0 = time.monotonic()
    while time.monotonic() - t0 < 60.0:
        job: dict[str, Any] = c.get(f"/api/experiments/{name}/export/derived/status").json()
        if job["state"] in ("done", "error"):
            return job
        time.sleep(0.05)
    raise AssertionError("derived regenerate did not finish")


def test_regenerate_computes_missing_smart_series(tmp_path: Path) -> None:
    name = make_smart_run(tmp_path, n=6).name
    with _client(tmp_path) as c:
        assert c.post(f"/api/experiments/{name}/export/derived?video=false").status_code == 200
        job = _wait_derived(c, name)
        assert job["state"] == "done", job
        assert (tmp_path / name / "smart_roi" / "7.npz").is_file()
        text = (tmp_path / name / "exports" / "roi_series.csv").read_text()
        assert "part area px" in text and "no stored series" not in text


def test_regenerate_recomputes_stale_smart_series(tmp_path: Path) -> None:
    name = make_smart_run(tmp_path, n=6).name
    with _client(tmp_path) as c:
        assert _compute(c, name)["state"] == "done"
        mtime = (tmp_path / name / "smart_roi" / "7.npz").stat().st_mtime_ns
        # fresh series: regenerate must NOT recompute it
        c.post(f"/api/experiments/{name}/export/derived?video=false")
        assert _wait_derived(c, name)["state"] == "done"
        assert (tmp_path / name / "smart_roi" / "7.npz").stat().st_mtime_ns == mtime
        # edit the stored ROI (sensitivity) -> the stored series is stale
        edited = {**SMART, "sensitivity": 0.4}
        assert c.put(f"/api/experiments/{name}/rois", json={"rois": [edited]}).status_code == 200
        c.post(f"/api/experiments/{name}/export/derived?video=false")
        assert _wait_derived(c, name)["state"] == "done"
        assert (tmp_path / name / "smart_roi" / "7.npz").stat().st_mtime_ns != mtime
        text = (tmp_path / name / "exports" / "roi_series.csv").read_text()
        assert "sensitivity=0.4" in text


def test_playback_series_route_skips_smart_roi(tmp_path: Path) -> None:
    import json

    name = make_smart_run(tmp_path, n=6).name
    rois = json.dumps([
        SMART, {"id": 2, "kind": "rect", "x0": 10, "y0": 10, "x1": 30, "y1": 30},
    ])
    with _client(tmp_path) as c:
        r = c.get(f"/api/experiments/{name}/series", params={"rois": rois})
        assert r.status_code == 200, r.text
        assert set(r.json()["series"]) == {"2"}  # smart data comes from the smart-roi routes
