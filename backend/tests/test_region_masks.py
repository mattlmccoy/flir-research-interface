"""Region masks: which pixels drive the colour auto-range and the frame stats.

A mask is a list of include/exclude polygons and rectangles in image pixels. It is stored with the
recording (``metadata.json['masks']``) and can be edited per run in playback. The thermal counts are
never touched, and masks are not ROIs (no series, no plot, not in roi_series.csv).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flir_research_interface.analysis.run_summary import readme_text
from flir_research_interface.api.app import create_app
from flir_research_interface.playback.reader import ExperimentReader

MASKS = [
    {
        "id": 1,
        "kind": "polygon",
        "points": [[10, 10], [40, 10], [40, 30], [10, 30]],
        "mode": "include",
    },
    {"id": 2, "kind": "rect", "x0": 0, "y0": 0, "x1": 8, "y1": 4, "mode": "exclude"},
]


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            default_backend="simulated", sim_fps=60.0, experiments_root=tmp_path, min_free_gb=0.0
        )
    )


def _record(c: TestClient, **body: object) -> Path:
    devs = c.get("/api/camera/devices").json()
    c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
    r = c.post("/api/recording/start", json={"name": "masked", **body})
    assert r.status_code == 200, r.text
    time.sleep(0.2)
    assert c.post("/api/recording/stop").status_code == 200
    return Path(r.json()["experiment_dir"])


def test_parse_masks_keeps_polygons_and_rects_with_their_mode() -> None:
    from flir_research_interface.analysis.masks import parse_masks

    assert parse_masks(MASKS) == MASKS


@pytest.mark.parametrize(
    "bad",
    [
        "not a list",
        [{"id": 1, "kind": "polygon", "points": [[0, 0], [5, 5]], "mode": "include"}],  # 2 points
        [{"id": 1, "kind": "rect", "x0": 0, "y0": 0, "x1": 4, "y1": 4, "mode": "keep"}],
        [{"id": 1, "kind": "spot", "x": 3, "y": 3, "mode": "include"}],
        [{"id": 1, "kind": "rect", "x0": 0, "y0": 0, "x1": "a", "y1": 4, "mode": "exclude"}],
    ],
)
def test_parse_masks_rejects_what_cannot_be_rasterised(bad: object) -> None:
    from flir_research_interface.analysis.masks import parse_masks

    with pytest.raises(ValueError):
        parse_masks(bad)


def test_masks_in_force_at_record_time_are_stored_with_the_recording(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        d = _record(c, masks=MASKS)
        meta = json.loads((d / "metadata.json").read_text())
        assert meta["masks"] == MASKS
        assert c.get(f"/api/experiments/{d.name}").json()["masks"] == MASKS
        c.post("/api/camera/disconnect")


def test_a_recording_without_masks_reports_none(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        d = _record(c)
        assert "masks" not in json.loads((d / "metadata.json").read_text())
        assert c.get(f"/api/experiments/{d.name}").json()["masks"] is None
        c.post("/api/camera/disconnect")


def test_playback_edits_replace_the_runs_masks_and_record_the_edit(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        d = _record(c, masks=MASKS)
        counts_before = (d / "thermal.zarr").stat().st_mtime_ns
        r = c.put(f"/api/experiments/{d.name}/masks", json={"masks": MASKS[1:]})
        assert r.status_code == 200 and r.json() == {"masks": 1}
        meta = json.loads((d / "metadata.json").read_text())
        assert meta["masks"] == MASKS[1:]
        assert meta["edits"][-1]["keys"] == ["masks"]
        assert (d / "thermal.zarr").stat().st_mtime_ns == counts_before  # raw data untouched
        bad = c.put(f"/api/experiments/{d.name}/masks", json={"masks": [{"kind": "spot"}]})
        assert bad.status_code == 400
        assert c.put("/api/experiments/nope/masks", json={"masks": []}).status_code == 404
        c.post("/api/camera/disconnect")


def test_readme_lists_the_masks_and_what_they_affect(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        d = _record(c, masks=MASKS)
        c.post("/api/camera/disconnect")
    txt = readme_text(ExperimentReader(d))
    assert "Region masks at record time: 2" in txt
    assert "include: polygon" in txt and "exclude: rect" in txt
    assert "colour range and frame stats only" in txt
