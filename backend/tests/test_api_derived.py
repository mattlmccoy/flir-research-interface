"""Re-export after editing ROIs in playback.

Bench bug: ROIs are stored only at record time; there was no way to persist ROIs added during
playback, so re-running any derived export regenerated from the original ROIs. These cover the
persist route (PUT rois) and the on-demand derived regenerate.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.visible.recorder import FFMPEG_CANDIDATES
from flir_research_interface.visible.rtsp import find_ffprobe

_HAVE_FFMPEG = find_ffprobe(FFMPEG_CANDIDATES) is not None

RECORD_ROIS = [{"id": 1, "kind": "spot", "x": 10, "y": 10, "name": "centre"}]
NEW_ROIS = [
    {"id": 1, "kind": "spot", "x": 10, "y": 10, "name": "centre"},
    {"id": 2, "kind": "rect", "x0": 0, "y0": 0, "x1": 20, "y1": 20, "name": "patch",
     "emissivity": 0.85},
]


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            default_backend="simulated", sim_fps=60.0, experiments_root=tmp_path, min_free_gb=0.0
        )
    )


def _wait_derived(c: TestClient, name: str, timeout: float = 30.0) -> dict:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        job = c.get(f"/api/experiments/{name}/export/derived/status").json()
        if job["state"] in ("done", "error"):
            return job
        time.sleep(0.1)
    raise AssertionError("derived job did not finish in time")


def _record(c: TestClient) -> str:
    devs = c.get("/api/camera/devices").json()
    c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
    r = c.post("/api/recording/start", json={"name": "run", "rois": RECORD_ROIS})
    assert r.status_code == 200, r.text
    name = Path(r.json()["experiment_dir"]).name
    time.sleep(0.3)
    assert c.post("/api/recording/stop").status_code == 200
    return name


def test_put_rois_updates_metadata_and_keeps_optics(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        name = _record(c)
        r = c.put(f"/api/experiments/{name}/rois", json={"rois": NEW_ROIS})
        assert r.status_code == 200, r.text
        assert r.json()["rois"] == 2
        meta = json.loads((tmp_path / name / "metadata.json").read_text())
        assert [x["kind"] for x in meta["rois"]] == ["spot", "rect"]
        assert meta["rois"][1]["name"] == "patch"
        assert meta["rois"][1]["emissivity"] == 0.85  # optics preserved for accuracy
        c.post("/api/camera/disconnect")


@pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg not installed")
def test_derived_regenerate_reflects_the_new_rois(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        name = _record(c)
        # at record time roi_series.csv had only the spot S1
        csv0 = (tmp_path / name / "exports" / "roi_series.csv").read_text()
        head0 = [ln for ln in csv0.splitlines() if not ln.startswith("#")][0]
        assert "R2_mean" not in head0

        c.put(f"/api/experiments/{name}/rois", json={"rois": NEW_ROIS})
        r = c.post(f"/api/experiments/{name}/export/derived")
        assert r.status_code == 200, r.text
        assert r.json()["state"] == "running"  # returns immediately, work runs in the background

        # poll the progress endpoint until the job finishes
        job = _wait_derived(c, name)
        assert job["state"] == "done", job
        names = {e["name"] for e in job["exports"]}
        assert "roi_series.csv" in names and "roi_plot.png" in names

        csv1 = (tmp_path / name / "exports" / "roi_series.csv").read_text()
        head1 = [ln for ln in csv1.splitlines() if not ln.startswith("#")][0]
        assert "R2_mean" in head1  # the rectangle now appears in the regenerated series
        c.post("/api/camera/disconnect")
