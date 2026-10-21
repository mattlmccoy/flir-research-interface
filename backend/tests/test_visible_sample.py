"""Visible-camera sample analysis: ROI selection and geometry on the real 20261020_144402 run.

The fixture (tests/fixtures/README.md) holds that run's ``visible_alignment``, ``rois``, packet
table and luma crops, captured from the real recording rather than authored.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from flir_research_interface.analysis.visible_sample import (
    FrameMetrics,
    frame_metrics,
    ir_to_visible_points,
    otsu_threshold,
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


@pytest.fixture(scope="module")
def region(run: dict[str, Any]) -> np.ndarray:
    """The boolean analysis-region mask (mapped freehand_sample, margin 30) of the real run."""
    out = region_mask(_sample_outline_vis(run), 30)
    assert out is not None
    return out[0]


@pytest.fixture(scope="module")
def crops() -> dict[int, np.ndarray]:
    """The fixture's luma crops by frame index (3170, 6141-6143 and 3-26)."""
    npz = np.load(FIXTURES / "visible_sample_20261020_144402.npz")
    return {int(f): npz["crops"][i] for i, f in enumerate(npz["crop_frames"].tolist())}


FIRST_5S = range(3, 27)  # the 24 analysed frames of the first 5 s: the frames 0-2 are skipped


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
    assert reach[1][2] % 2 == 0 and reach[1][3] % 2 == 0
    # straddling the left edge: the clipped region is 51 x 121 px, widened to 52 x 122
    left = region_mask(_square(-40, 100, 60), 30)
    assert left is not None
    assert left[1][0] == 0
    assert left[1][2] % 2 == 0 and left[1][3] % 2 == 0


def test_region_mask_odd_bbox_is_widened_with_blank_pixels() -> None:
    # straddling the left edge, the tight bbox has an odd width and height (51 x 121 px): the extra
    # column and row go on the right and bottom and hold no region pixels
    out = region_mask(_square(-40, 100, 60), 30)
    assert out is not None
    mask, (x0, y0, w, h) = out
    assert (x0, w % 2, h % 2) == (0, 0, 0)
    assert mask.shape == (h, w)
    assert not mask[:, -1].any() and not mask[-1, :].any()
    assert mask[:, :-1].any(axis=0).all() and mask[:-1, :].any(axis=1).all()


def test_region_mask_odd_bbox_at_far_edge_widens_up_and_left() -> None:
    # the tight bbox ends at the right and bottom frame edge with an odd width and height
    # (79 x 99 px), so the extra column and row go on the left and top
    out = region_mask(_square(1231, 891, 60), 30)
    assert out is not None
    mask, (x0, y0, w, h) = out
    assert (x0 + w, y0 + h) == VIS_SIZE
    assert (w % 2, h % 2) == (0, 0)
    assert mask.shape == (h, w)
    assert not mask[:, 0].any() and not mask[0, :].any()
    assert mask[:, 1:].any(axis=0).all() and mask[1:, :].any(axis=1).all()


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


def test_otsu_threshold_real_first_5s(region: np.ndarray, crops: dict[int, np.ndarray]) -> None:
    pooled = np.concatenate([crops[i][region] for i in FIRST_5S])
    assert pooled.size == 24 * 13543
    assert otsu_threshold(pooled) == 178


def test_otsu_threshold_separates_two_modes_and_rejects_empty() -> None:
    low = np.arange(20, 61, dtype=np.uint8)
    high = np.arange(180, 221, dtype=np.uint8)
    assert 60 <= otsu_threshold(np.concatenate([low, high])) < 180
    with pytest.raises(ValueError):
        otsu_threshold(np.array([], dtype=np.uint8))


def test_dark_area_real_start(region: np.ndarray, crops: dict[int, np.ndarray]) -> None:
    dark = [frame_metrics(crops[i], None, region, 178).sample_dark_px for i in FIRST_5S]
    assert len(dark) == 24
    assert np.mean(dark) == pytest.approx(1095, rel=0.01)
    assert dark[0] == pytest.approx(1100, rel=0.01)  # frame 3 alone
    assert all(isinstance(n, int) for n in dark)


def test_brightening_glow_frames(region: np.ndarray, crops: dict[int, np.ndarray]) -> None:
    before, during, after = crops[6141], crops[6142], crops[6143]
    assert frame_metrics(during, before, region, 178).brightening == pytest.approx(97, abs=1)
    assert frame_metrics(after, during, region, 178).brightening == pytest.approx(27, abs=1)
    assert frame_metrics(before, before.copy(), region, 178).brightening == 0


def test_frame_metrics_no_prev(region: np.ndarray, crops: dict[int, np.ndarray]) -> None:
    metrics = frame_metrics(crops[3], None, region, 178)
    assert metrics.brightening is None
    assert metrics.bed_clipped_frac is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        metrics.sample_dark_px = 0  # type: ignore[misc]


def test_frame_metrics_counts_region_pixels_strictly_below_threshold() -> None:
    luma = np.array([[100, 177, 178, 179], [180, 10, 20, 30]], dtype=np.uint8)
    region = np.array([[True, True, True, True], [True, False, False, False]])
    assert frame_metrics(luma, None, region, 178) == FrameMetrics(
        sample_dark_px=2, sample_mean_luma=138.5, bed_clipped_frac=None, brightening=None
    )


def test_frame_metrics_without_dark_pixels_has_no_mean() -> None:
    luma = np.full((4, 4), 200, dtype=np.uint8)
    metrics = frame_metrics(luma, None, np.ones((4, 4), dtype=bool), 178)
    assert (metrics.sample_dark_px, metrics.sample_mean_luma) == (0, None)


def test_frame_metrics_brightening_is_signed_percentile_over_region() -> None:
    prev = np.full((10, 20), 100, dtype=np.uint8)
    luma = prev.copy()
    luma[0, 10:] = 160  # +60 on 10 of the 100 region pixels
    luma[5, 0] = 255  # +155, but outside the region
    region = np.zeros((10, 20), dtype=bool)
    region[:, 10:] = True
    assert frame_metrics(luma, prev, region, 50).brightening == pytest.approx(60.0)
    # reversed, the same pixels change by -60: a uint8 subtraction would wrap them to 196
    assert frame_metrics(prev, luma, region, 50).brightening == pytest.approx(0.0)


def test_frame_metrics_empty_region_has_no_brightening() -> None:
    luma = np.full((4, 4), 100, dtype=np.uint8)
    metrics = frame_metrics(luma, luma.copy(), np.zeros((4, 4), dtype=bool), 178)
    assert metrics == FrameMetrics(0, None, None, None)


def test_bed_clipped_frac() -> None:
    region = np.ones((4, 4), dtype=bool)
    bed = np.zeros((4, 4), dtype=bool)
    bed[:2, :] = True
    white = np.full((4, 4), 255, dtype=np.uint8)
    assert frame_metrics(white, None, region, 178, bed).bed_clipped_frac == 1.0
    assert frame_metrics(white, None, region, 178).bed_clipped_frac is None
    half = white.copy()
    half[0, :2] = 254  # 2 of the 8 bed pixels fall just short of 255
    assert frame_metrics(half, None, region, 178, bed).bed_clipped_frac == 0.75
    assert frame_metrics(white, None, region, 178, np.zeros_like(bed)).bed_clipped_frac is None
