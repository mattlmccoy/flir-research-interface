"""Visible-camera sample analysis on the real 20261020_144402 run: ROI geometry, per-frame metrics,
flash events and coverage.

The fixture (tests/fixtures/README.md) holds that run's ``visible_alignment``, ``rois``, packet
table, luma crops and per-frame ``brightening``, captured from the real recording rather than
authored.
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
    coverage,
    find_events,
    flash_threshold,
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


@pytest.fixture(scope="module")
def series(run: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(t_s, brightening, keyframe)`` of all 6,192 frames of the real run.

    ``t_s`` is the frame time on the thermal axis, ``t_start_s + pts - pts[0]``; ``brightening`` is
    NaN for frames 0-3. Treat the arrays as read-only: copy before changing them.
    """
    pts = np.asarray(run["packets"]["pts_time"], dtype=float)
    t_s = run["t_start_s"] + pts - pts[0]
    npz = np.load(FIXTURES / "visible_sample_20261020_144402.npz")
    brightening, keyframe = npz["brightening"], npz["keyframe"]
    assert len(t_s) == len(brightening) == len(keyframe) == 6192
    return t_s, brightening, keyframe


# The three flash events measured on the real run: (t_start_s, t_end_s, peak, peak_frame, n_frames)
REAL_EVENTS = [
    (553.95, 554.06, 20, 5303, 2),
    (615.66, 615.85, 19, 6005, 2),
    (627.77, 629.41, 97, 6142, 7),
]


def test_flash_threshold_real_run_floor_binds(
    series: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    _, brightening, keyframe = series
    assert flash_threshold(brightening, keyframe) == 15.0


def test_flash_threshold_mad_zero() -> None:
    keyframe = np.zeros(50, dtype=bool)
    # every value equal: MAD is 0, floored at 1, so the rule is median + 6
    assert flash_threshold(np.full(50, 20.0), keyframe) == 26.0
    assert flash_threshold(np.full(50, 5.0), keyframe) == 15.0  # median + 6 = 11: the floor binds


def test_flash_threshold_uses_scaled_mad_and_ignores_keyframes_and_nan() -> None:
    values = np.array([10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0])  # median 16, raw MAD 4
    expected = 16.0 + 6.0 * 1.4826 * 4.0
    assert flash_threshold(values, np.zeros(7, dtype=bool)) == pytest.approx(expected)
    noisy = np.append(values, [500.0, np.nan])
    keyframe = np.array([False] * 7 + [True, False])
    assert flash_threshold(noisy, keyframe) == pytest.approx(expected)
    assert flash_threshold(values, np.zeros(7, dtype=bool), floor=100.0) == 100.0
    assert flash_threshold(values, np.zeros(7, dtype=bool), k=2.0) == pytest.approx(
        max(15.0, 16.0 + 2.0 * 1.4826 * 4.0)
    )


def test_flash_threshold_without_usable_values_is_the_floor() -> None:
    empty = np.array([])
    assert flash_threshold(empty, empty.astype(bool)) == 15.0
    assert flash_threshold(np.full(4, np.nan), np.zeros(4, dtype=bool)) == 15.0
    assert flash_threshold(np.full(4, 99.0), np.ones(4, dtype=bool)) == 15.0
    assert flash_threshold(empty, empty.astype(bool), floor=7.5) == 7.5


def test_find_events_real_run_three_events(
    series: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    t_s, brightening, keyframe = series
    events = find_events(t_s, brightening, keyframe, flash_threshold(brightening, keyframe))
    assert len(events) == 3
    for event, (t_start, t_end, peak, frame, n_frames) in zip(events, REAL_EVENTS, strict=True):
        assert set(event) == {
            "t_start_s", "t_peak_s", "t_end_s", "peak_brightening", "n_frames", "peak_frame"
        }
        assert event["t_start_s"] == pytest.approx(t_start, abs=0.02)
        assert event["t_end_s"] == pytest.approx(t_end, abs=0.02)
        assert event["peak_brightening"] == pytest.approx(peak, abs=1)
        assert event["peak_frame"] == frame
        assert event["t_peak_s"] == pytest.approx(t_s[frame])
        assert event["peak_brightening"] == pytest.approx(brightening[frame])
        assert event["n_frames"] == n_frames
        # plain Python numbers, so the summary JSON can hold them
        assert type(event["peak_frame"]) is int and type(event["n_frames"]) is int
        assert all(type(event[k]) is float for k in event if k not in ("peak_frame", "n_frames"))


def test_find_events_no_event_at_glitch(
    series: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    # the 413.65 s decoding glitch must not produce an event
    t_s, brightening, keyframe = series
    events = find_events(t_s, brightening, keyframe, flash_threshold(brightening, keyframe))
    assert not [e for e in events if e["t_start_s"] <= 414.0 and e["t_end_s"] >= 413.3]


def test_find_events_merge_window(series: tuple[np.ndarray, np.ndarray, np.ndarray]) -> None:
    # event 3 ends with a frame 0.517 s after the one before it (628.894 s -> 629.411 s): a 0.5 s
    # merge window splits it in two, a 1.0 s window keeps it whole
    t_s, brightening, keyframe = series
    threshold = flash_threshold(brightening, keyframe)
    events = find_events(t_s, brightening, keyframe, threshold, merge_s=0.5)
    assert len(events) == 4
    assert [e["peak_frame"] for e in events[:3]] == [5303, 6005, 6142]
    third, fourth = events[2], events[3]
    assert third["t_start_s"] == pytest.approx(627.77, abs=0.02)
    assert third["t_end_s"] == pytest.approx(628.894, abs=0.02)
    assert fourth["t_start_s"] == pytest.approx(629.411, abs=0.02)
    assert fourth["t_end_s"] == fourth["t_start_s"]
    assert third["n_frames"] + fourth["n_frames"] == 7
    assert len(find_events(t_s, brightening, keyframe, threshold, merge_s=1.0)) == 3


def test_keyframes_never_flag(series: tuple[np.ndarray, np.ndarray, np.ndarray]) -> None:
    t_s, brightening, keyframe = series
    spiked = brightening.copy()
    spiked[keyframe] = 200.0
    threshold = flash_threshold(spiked, keyframe)
    assert threshold == 15.0
    events = find_events(t_s, spiked, keyframe, threshold)
    assert [(e["peak_frame"], e["n_frames"]) for e in events] == [(5303, 2), (6005, 2), (6142, 7)]


def test_find_events_none(series: tuple[np.ndarray, np.ndarray, np.ndarray]) -> None:
    t_s, _, keyframe = series
    quiet = np.zeros(len(t_s))
    assert find_events(t_s, quiet, keyframe, flash_threshold(quiet, keyframe)) == []
    assert find_events(np.array([]), np.array([]), np.array([], dtype=bool), 15.0) == []


def test_find_events_merge_chains_from_the_last_flagged_frame() -> None:
    # gaps of 0.5, 1.0 (exactly the window: joins), 1.0 and 1.5 s; the quiet frame at 3.0 s
    # and the unflagged keyframe at 3.5 s break nothing and flag nothing
    t_s = np.array([0.0, 0.5, 1.5, 2.5, 3.0, 3.5, 4.0])
    brightening = np.array([20.0, 50.0, 40.0, 30.0, 0.0, 99.0, 25.0])
    keyframe = np.array([False, False, False, False, False, True, False])
    first, second = find_events(t_s, brightening, keyframe, 15.0, merge_s=1.0)
    assert (first["t_start_s"], first["t_end_s"], first["n_frames"]) == (0.0, 2.5, 4)
    assert (first["peak_frame"], first["t_peak_s"], first["peak_brightening"]) == (1, 0.5, 50.0)
    assert (second["t_start_s"], second["t_end_s"], second["n_frames"]) == (4.0, 4.0, 1)
    assert second["peak_frame"] == 6
    # the threshold itself flags (>=), and nothing below it does
    assert [e["peak_frame"] for e in find_events(t_s, brightening, keyframe, 25.0)] == [1, 6]
    assert [e["peak_frame"] for e in find_events(t_s, brightening, keyframe, 25.5)] == [1]


def test_coverage_real_run(series: tuple[np.ndarray, np.ndarray, np.ndarray]) -> None:
    t_s, _, _ = series
    analysed = t_s[3:]  # frames 0-2 fall in the first 0.25 s and are skipped
    result = coverage(analysed)
    assert result["frames_analysed"] == len(analysed) == 6189
    assert result["t_first_s"] == pytest.approx(t_s[3])
    assert result["t_last_s"] == pytest.approx(t_s[-1])
    assert result["gaps_over_300ms"] == 61
    assert coverage(t_s)["gaps_over_300ms"] == 62  # the run's 62nd gap lies in the skipped 0.25 s


def test_coverage_counts_gaps_over_300ms_and_handles_short_inputs() -> None:
    result = coverage(np.array([0.0, 0.125, 0.5, 0.75, 1.25]))  # gaps 0.125, 0.375, 0.25, 0.5
    assert result == {
        "frames_analysed": 5, "t_first_s": 0.0, "t_last_s": 1.25, "gaps_over_300ms": 2
    }
    assert coverage(np.array([3.5])) == {
        "frames_analysed": 1, "t_first_s": 3.5, "t_last_s": 3.5, "gaps_over_300ms": 0
    }
    assert coverage(np.array([])) == {
        "frames_analysed": 0, "t_first_s": None, "t_last_s": None, "gaps_over_300ms": 0
    }
