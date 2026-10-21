"""Visible-camera sample analysis: ROI selection and geometry on the real 20261020_144402 run.

The fixture (tests/fixtures/README.md) holds that run's ``visible_alignment``, ``rois``, packet
table and luma crops, captured from the real recording rather than authored.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from flir_research_interface.analysis.visible_sample import (
    ir_to_visible_points,
    pick_rois,
    region_mask,
    roi_outline_ir,
)

FIXTURES = Path(__file__).parent / "fixtures"
VIS_SIZE = (1280, 960)


@pytest.fixture(scope="module")
def run() -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(
        (FIXTURES / "visible_sample_20261020_144402.json").read_text()
    )
    return doc


def _sample_outline_vis(run: dict[str, Any]) -> np.ndarray:
    sample, _ = pick_rois(run["rois"])
    assert sample is not None
    return ir_to_visible_points(roi_outline_ir(sample), run["visible_alignment"]["H"])


def _square(x0: float, y0: float, side: float) -> np.ndarray:
    return np.array(
        [[x0, y0], [x0 + side, y0], [x0 + side, y0 + side], [x0, y0 + side]], dtype=float
    )


def test_pick_rois_real_run(run: dict[str, Any]) -> None:
    sample, bed = pick_rois(run["rois"])
    assert sample is not None and bed is not None
    assert (sample["id"], sample["name"]) == (101, "freehand_sample")
    assert (bed["id"], bed["name"]) == (94, "powder")


def test_pick_rois_smallest_sample_wins() -> None:
    big = {"id": 1, "kind": "polygon", "points": [[0, 0], [100, 0], [100, 100], [0, 100]],
           "name": "SAMPLE big"}
    small = {"id": 2, "kind": "polygon", "points": [[0, 0], [10, 0], [10, 10], [0, 10]],
             "name": "sample small"}
    nameless = {"id": 3, "kind": "polygon", "points": [[0, 0], [2, 0], [2, 2], [0, 2]]}
    sample, bed = pick_rois([big, nameless, small])
    assert sample is small
    assert bed is None


def test_pick_rois_none() -> None:
    spot = {"id": 1, "kind": "spot", "x": 5, "y": 6, "name": "sample"}
    assert pick_rois([]) == (None, None)
    assert pick_rois(None) == (None, None)
    assert pick_rois([spot]) == (None, None)


def test_freehand_sample_maps_onto_video_sample(run: dict[str, Any]) -> None:
    pts = _sample_outline_vis(run)
    assert pts.min(axis=0)[0] == pytest.approx(347, abs=2)
    assert pts.max(axis=0)[0] == pytest.approx(411, abs=2)
    assert pts.min(axis=0)[1] == pytest.approx(405, abs=2)
    assert pts.max(axis=0)[1] == pytest.approx(469, abs=2)


def test_roi_outline_circle_and_rect() -> None:
    circle = roi_outline_ir({"id": 94, "kind": "circle", "cx": 147, "cy": 216, "r": 67.0})
    assert circle.shape == (64, 2)
    dist = np.hypot(circle[:, 0] - 147, circle[:, 1] - 216)
    assert dist == pytest.approx(np.full(64, 67.0))
    rect = roi_outline_ir({"id": 1, "kind": "rect", "x0": 1, "y0": 0, "x1": 5, "y1": 4})
    assert sorted(map(tuple, rect.tolist())) == [(1, 0), (1, 4), (5, 0), (5, 4)]
    ellipse = roi_outline_ir(
        {"id": 2, "kind": "ellipse", "cx": 10, "cy": 20, "rx": 6.0, "ry": 3.0}, n_circle=16
    )
    assert ellipse.shape == (16, 2)
    on_ellipse = ((ellipse[:, 0] - 10) / 6.0) ** 2 + ((ellipse[:, 1] - 20) / 3.0) ** 2
    assert on_ellipse == pytest.approx(np.ones(16))
    with pytest.raises(ValueError):
        roi_outline_ir({"id": 3, "kind": "spot", "x": 1, "y": 2})


def test_region_mask_margin_and_even_bbox(run: dict[str, Any]) -> None:
    out = region_mask(_sample_outline_vis(run), 30)
    assert out is not None
    mask, (x0, y0, w, h) = out
    assert mask.dtype == bool and mask.shape == (h, w)
    assert w % 2 == 0 and h % 2 == 0
    assert 0 <= x0 and x0 + w <= VIS_SIZE[0] and 0 <= y0 and y0 + h <= VIS_SIZE[1]
    assert mask.sum() == pytest.approx(13543, rel=0.01)


def test_region_mask_outside_frame_returns_none() -> None:
    assert region_mask(_square(1500, 100, 100), 30) is None
    assert region_mask(np.array([[np.nan, 0.0], [1.0, 1.0], [2.0, 0.0]]), 30) is None
    # outside the frame, but the margin reaches into it
    reach = region_mask(_square(1290, 100, 30), 30)
    assert reach is not None
    assert reach[1][0] + reach[1][2] == VIS_SIZE[0]
    # straddling the left edge
    left = region_mask(_square(-40, 100, 60), 30)
    assert left is not None
    assert left[1][0] == 0


def test_fixture_crops_match_region_mask(run: dict[str, Any]) -> None:
    out = region_mask(_sample_outline_vis(run), 30)
    assert out is not None
    _, (_, _, w, h) = out
    npz = np.load(FIXTURES / "visible_sample_20261020_144402.npz")
    frames = npz["crop_frames"].tolist()
    assert frames == [3170, 6141, 6142, 6143, *range(3, 27)]
    assert npz["crops"].shape == (len(frames), h, w)
    assert npz["crops"].dtype == np.uint8
    n = len(run["packets"]["pts_time"])
    assert n == 6192 and len(run["packets"]["keyframe"]) == n
    assert npz["brightening"].shape == (n,) and npz["keyframe"].shape == (n,)
