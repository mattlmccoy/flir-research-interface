"""Live per-ROI temperature feed for closed-loop control (GET /api/live/roi-temps).

The safety contract: an absent, stale, or over-range reading must come back valid:false with null
temps — never a plausible-looking number the RF controller could act on.
"""

from __future__ import annotations

import numpy as np

from flir_research_interface.analysis.live_temps import live_roi_payload

IRFMT = "TemperatureLinear10mK"  # 0.01 K/count


def _counts_for(celsius: float, shape=(480, 640)) -> np.ndarray:
    """Uniform frame whose every pixel reads ``celsius`` in 10 mK counts."""
    counts = round((celsius + 273.15) / 0.01)
    return np.full(shape, counts, dtype=np.uint16)


CIRCLE = {"id": 10, "name": "circle_medium_small", "kind": "circle",
          "cx": 320, "cy": 240, "r": 20.0}
SPOT = {"id": 45, "name": "trans_hotspot", "kind": "spot", "x": 100, "y": 100}


def test_fresh_area_roi_reports_mean_max_min_and_is_valid() -> None:
    counts = _counts_for(185.0)
    p = live_roi_payload(counts=counts, ir_format=IRFMT, rois=[CIRCLE], acquiring=True,
                         frame_id=7, host_ts_ns=1_000_000_000, now_ns=1_042_000_000)
    assert p["live"] is True and p["stale"] is False
    assert p["frame_id"] == 7
    assert p["frame_ts"].startswith("1970-01-01T00:00:01")  # ISO-8601 of host_ts
    assert abs(p["age_ms"] - 42.0) < 1e-6  # 42 ms old
    (roi,) = p["rois"]
    assert roi["name"] == "circle_medium_small" and roi["id"] == 10 and roi["valid"] is True
    assert abs(roi["mean_c"] - 185.0) < 0.05 and abs(roi["max_c"] - 185.0) < 0.05
    assert roi["value_c"] is None  # area ROI: no single-pixel value
    assert roi["over_range"] is False


def test_spot_roi_populates_value_c() -> None:
    p = live_roi_payload(counts=_counts_for(150.0), ir_format=IRFMT, rois=[SPOT], acquiring=True,
                         frame_id=1, host_ts_ns=2_000_000_000, now_ns=2_000_000_000)
    (roi,) = p["rois"]
    assert roi["kind"] == "spot" and roi["valid"] is True
    assert abs(roi["value_c"] - 150.0) < 0.05


def test_stale_frame_is_invalid_with_null_temps() -> None:
    # frame is 2 s old (> 1 s threshold): the whole feed goes stale and every ROI invalid
    p = live_roi_payload(counts=_counts_for(185.0), ir_format=IRFMT, rois=[CIRCLE], acquiring=True,
                         frame_id=7, host_ts_ns=1_000_000_000, now_ns=3_000_000_000)
    assert p["live"] is False and p["stale"] is True
    (roi,) = p["rois"]
    assert roi["valid"] is False and roi["mean_c"] is None and roi["max_c"] is None
    assert roi["name"] == "circle_medium_small"  # roster still listed, just invalid


def test_no_camera_is_invalid_not_a_healthy_zero() -> None:
    p = live_roi_payload(counts=None, ir_format=None, rois=[CIRCLE], acquiring=False,
                         frame_id=None, host_ts_ns=None, now_ns=5_000_000_000)
    assert p["live"] is False and p["stale"] is True
    assert p["frame_id"] is None and p["frame_ts"] is None
    (roi,) = p["rois"]
    assert roi["valid"] is False and roi["mean_c"] is None


def test_over_range_roi_trips_invalid() -> None:
    # saturate the control ROI's pixels; its max would understate the true temperature, so the
    # whole ROI must fail safe (valid:false), not report a number from the unsaturated pixels.
    counts = _counts_for(185.0)
    counts[220:260, 300:340] = 65000  # covers the circle at (320,240) r=20
    p = live_roi_payload(counts=counts, ir_format=IRFMT, rois=[CIRCLE], acquiring=True,
                         frame_id=9, host_ts_ns=1_000_000_000, now_ns=1_000_010_000)
    (roi,) = p["rois"]
    assert roi["over_range"] is True and roi["valid"] is False
    assert roi["mean_c"] is None and roi["max_c"] is None


def test_rect_roi_is_measured_like_the_recorded_series() -> None:
    # Drawing a rectangle in the live view crashed the whole feed (KeyError 'points', 2026-10-13):
    # roi_index had no rect branch. Pixels must match the recorded series: [y0:y1, x0:x1].
    counts = _counts_for(25.0)
    hot = round((185.0 + 273.15) / 0.01)
    counts[100:110, 200:220] = hot  # exactly the rect below → every pixel hot
    rect = {"id": 3, "name": "coupon", "kind": "rect", "x0": 200, "y0": 100, "x1": 220, "y1": 110}
    p = live_roi_payload(counts=counts, ir_format=IRFMT, rois=[rect, CIRCLE], acquiring=True,
                         frame_id=1, host_ts_ns=1_000_000_000, now_ns=1_010_000_000)
    r, c = p["rois"]
    assert r["valid"] is True and r["kind"] == "rect"
    assert abs(r["mean_c"] - 185.0) < 0.05 and abs(r["min_c"] - 185.0) < 0.05  # no edge leakage
    assert c["valid"] is True  # the other ROI is still measured


def test_one_bad_roi_is_invalid_and_never_breaks_the_feed() -> None:
    counts = _counts_for(100.0)
    bad = {"id": 9, "name": "half-drawn", "kind": "polygon"}  # no points yet
    odd = {"id": 8, "name": "future", "kind": "hexagon", "points": [[1, 1], [5, 5], [1, 5]]}
    p = live_roi_payload(counts=counts, ir_format=IRFMT, rois=[bad, odd, SPOT], acquiring=True,
                         frame_id=1, host_ts_ns=1_000_000_000, now_ns=1_010_000_000)
    by = {r["id"]: r for r in p["rois"]}
    assert by[9]["valid"] is False and by[9]["mean_c"] is None  # fails safe, not a fake number
    assert by[8]["valid"] is False  # unknown kinds are not guessed as polygons
    assert by[45]["valid"] is True and abs(by[45]["value_c"] - 100.0) < 0.05
