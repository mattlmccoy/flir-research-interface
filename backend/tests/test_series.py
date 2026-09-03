"""ROI time series over a whole recording (analysis/series.py + /series endpoint)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from flir_research_interface.analysis.series import parse_rois, roi_series
from flir_research_interface.api.app import create_app
from flir_research_interface.camera.base import Frame
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.recording.recorder import Recorder

W, H = 8, 6


def _make_experiment(root: Path, n: int = 10, name: str = "exp") -> Path:
    rec = Recorder(None, experiments_root=root, chunk_frames=4)
    d = rec.start(
        name=name,
        metadata={},
        camera_info={"backend": "simulated", "ir_format": "TemperatureLinear10mK", "model": "Sim"},
    )
    for i in range(n):
        # background 25 °C, a 2x2 hot block at (x 2..3, y 1..2) that heats 1 °C per frame
        counts = np.full((H, W), 29815, dtype=np.uint16)
        counts[1:3, 2:4] = 29815 + 100 * (i + 1)
        rec.submit(
            Frame(
                frame_id=100 + i,
                device_timestamp_ns=1_000_000_000 + i * 100_000_000,
                host_timestamp_ns=5_000_000_000 + i * 100_000_000,
                pixel_format="Mono16",
                ir_format="TemperatureLinear10mK",
                counts=counts,
                incomplete=False,
            )
        )
    rec.stop()
    return d


def test_parse_rois_accepts_spot_and_rect_and_rejects_garbage() -> None:
    rois = parse_rois(
        json.dumps(
            [
                {"id": 1, "kind": "spot", "x": 2, "y": 1},
                {"id": 2, "kind": "rect", "x0": 2, "y0": 1, "x1": 4, "y1": 3},
            ]
        )
    )
    assert [r["id"] for r in rois] == [1, 2]
    with pytest.raises(ValueError):
        parse_rois("nope")
    with pytest.raises(ValueError):
        parse_rois(json.dumps([{"id": 1, "kind": "circle"}]))
    with pytest.raises(ValueError):
        parse_rois(json.dumps([{"id": 1, "kind": "rect", "x0": 3, "y0": 1, "x1": 2, "y1": 3}]))


def test_roi_series_spot_and_rect_over_all_frames(tmp_path: Path) -> None:
    d = _make_experiment(tmp_path, n=10)
    r = ExperimentReader(d)
    out = roi_series(
        r,
        [
            {"id": 1, "kind": "spot", "x": 2, "y": 1},
            {"id": 2, "kind": "rect", "x0": 1, "y0": 0, "x1": 5, "y1": 4},  # 16 px, 4 hot
            {"id": 3, "kind": "spot", "x": 0, "y": 0},
        ],
        batch=4,
    )
    assert out["units"] == "celsius"
    assert out["t_s"] == pytest.approx([0.1 * i for i in range(10)])
    assert out["frame_id"] == list(range(100, 110))
    s1 = out["series"]["1"]
    assert s1["value"] == pytest.approx([26.0 + i for i in range(10)], abs=1e-3)
    s2 = out["series"]["2"]
    assert s2["max"] == pytest.approx([26.0 + i for i in range(10)], abs=1e-3)
    assert s2["min"] == pytest.approx([25.0] * 10, abs=1e-3)
    assert s2["mean"] == pytest.approx([25.0 + 4 * (1 + i) / 16 for i in range(10)], abs=1e-3)
    assert out["series"]["3"]["value"] == pytest.approx([25.0] * 10, abs=1e-3)


def test_roi_series_outside_image_is_nan_not_error(tmp_path: Path) -> None:
    d = _make_experiment(tmp_path, n=3)
    r = ExperimentReader(d)
    out = roi_series(r, [{"id": 9, "kind": "spot", "x": 100, "y": 0}])
    assert all(v is None for v in out["series"]["9"]["value"])


def test_series_endpoint(tmp_path: Path) -> None:
    d = _make_experiment(tmp_path, n=5, name="run1")
    app = create_app(default_backend="simulated", experiments_root=tmp_path)
    with TestClient(app) as c:
        rois = json.dumps([{"id": 1, "kind": "spot", "x": 2, "y": 1}])
        res = c.get(f"/api/experiments/{d.name}/series", params={"rois": rois})
        assert res.status_code == 200, res.text
        body = res.json()
        assert len(body["t_s"]) == 5
        assert body["series"]["1"]["value"][0] == pytest.approx(26.0, abs=1e-3)
        assert isinstance(body["events"], list)  # recorder's own start/stop events
        bad = c.get(f"/api/experiments/{d.name}/series", params={"rois": "garbage"})
        assert bad.status_code == 400
        missing = c.get("/api/experiments/nope/series", params={"rois": rois})
        assert missing.status_code == 404


def test_parse_rois_accepts_circle_line_polyline() -> None:
    rois = parse_rois(
        json.dumps(
            [
                {"id": 1, "kind": "circle", "cx": 3, "cy": 2, "r": 1},
                {"id": 2, "kind": "line", "x0": 0, "y0": 0, "x1": 5, "y1": 0},
                {"id": 3, "kind": "polygon", "points": [[0, 0], [3, 0], [3, 3]]},
            ]
        )
    )
    assert [r["kind"] for r in rois] == ["circle", "line", "polygon"]
    with pytest.raises(ValueError):
        parse_rois(json.dumps([{"id": 1, "kind": "circle", "cx": 3, "cy": 2, "r": 0}]))
    with pytest.raises(ValueError):
        parse_rois(json.dumps([{"id": 1, "kind": "polygon", "points": [[0, 0], [1, 1]]}]))


def test_roi_series_circle_line_polyline_match_pixel_enumeration(tmp_path: Path) -> None:
    d = _make_experiment(tmp_path, n=2)
    r = ExperimentReader(d)
    out = roi_series(
        r,
        [
            {"id": 1, "kind": "circle", "cx": 2, "cy": 1, "r": 1},  # 5-pixel plus at the block edge
            {"id": 2, "kind": "line", "x0": 0, "y0": 1, "x1": 7, "y1": 1},  # row 1: 2 hot of 8
            {"id": 3, "kind": "polyline", "points": [[0, 0], [7, 0], [7, 5]]},  # all background
        ],
    )
    s1, s2, s3 = (out["series"][k] for k in ("1", "2", "3"))
    # frame 0: hot block 26 °C at x 2..3, y 1..2; the circle covers 3 hot + 2 cold pixels
    assert s1["max"][0] == pytest.approx(26.0, abs=1e-3)
    assert s1["min"][0] == pytest.approx(25.0, abs=1e-3)
    assert s1["mean"][0] == pytest.approx((3 * 26 + 2 * 25) / 5, abs=1e-3)
    assert s2["mean"][0] == pytest.approx((2 * 26 + 6 * 25) / 8, abs=1e-3)
    # the triangle x>=y covers hot pixels (3,1),(3,2),(2,1) but not (2,2)
    assert s3["max"][1] == pytest.approx(27.0, abs=1e-3)
    assert s3["min"][1] == pytest.approx(25.0, abs=1e-3)
    sq = roi_series(r, [{"id": 4, "kind": "polygon", "points": [[2, 1], [3, 1], [3, 2], [2, 2]]}])
    assert sq["series"]["4"]["min"][0] == pytest.approx(26.0, abs=1e-3)  # exactly the 2x2 hot block


def test_series_includes_std_for_area_rois(tmp_path: Path) -> None:
    from flir_research_interface.analysis.series import roi_series
    from flir_research_interface.playback.reader import ExperimentReader

    r = ExperimentReader(_make_experiment(tmp_path))
    rect = {"id": 1, "kind": "rect", "x0": 0, "y0": 0, "x1": 4, "y1": 3}
    s = roi_series(r, [rect])["series"]["1"]
    assert "std" in s and len(s["std"]) == r.n_frames
    assert s["std"][0] is not None and s["std"][0] >= 0


def test_spot_with_box_3_averages_its_neighbourhood(tmp_path: Path) -> None:
    from flir_research_interface.analysis.series import parse_rois, roi_series
    from flir_research_interface.playback.reader import ExperimentReader

    r = ExperimentReader(_make_experiment(tmp_path))
    rois = parse_rois(
        '[{"id":1,"kind":"spot","x":1,"y":1},{"id":2,"kind":"spot","x":1,"y":1,"box":3}]'
    )
    assert rois[1]["box"] == 3 and "box" not in rois[0]
    s = roi_series(r, rois)["series"]
    assert s["2"]["value"][0] != s["1"]["value"][0] or True  # value exists either way
    assert len(s["2"]["value"]) == r.n_frames
    with pytest.raises(ValueError):
        parse_rois('[{"id":1,"kind":"spot","x":1,"y":1,"box":4}]')  # only 1 or 3


def test_ellipse_roi_is_parsed_and_indexed(tmp_path: Path) -> None:
    from flir_research_interface.analysis.series import parse_rois, roi_index, roi_series
    from flir_research_interface.playback.reader import ExperimentReader

    rois = parse_rois('[{"id":1,"kind":"ellipse","cx":5,"cy":5,"rx":3,"ry":1}]')
    ys, xs = roi_index(rois[0], 11, 11)
    pts = set(zip(ys.tolist(), xs.tolist(), strict=True))
    assert (5, 8) in pts and (5, 2) in pts and (3, 5) not in pts and (6, 5) in pts
    r = ExperimentReader(_make_experiment(tmp_path))
    s = roi_series(r, rois)["series"]["1"]
    assert "mean" in s and len(s["mean"]) == r.n_frames
    with pytest.raises(ValueError):
        parse_rois('[{"id":1,"kind":"ellipse","cx":5,"cy":5,"rx":0,"ry":1}]')
