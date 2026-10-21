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


# --- smart ROIs (spec §7a/§7b): one flat entry + state, rings, dims ------------------------------

SMART = {"id": 7, "name": "sample", "kind": "smart", "search": [[100, 100], [300, 100], [300, 260]],
         "rings_px": [5, 10, 25], "rule": "relative", "fixed_c": None, "sensitivity": 0.5,
         "ring_emissivity": None}


def _smart_result(state: str = "holding", valid: bool = True):  # type: ignore[no-untyped-def]
    from flir_research_interface.analysis.smart_roi import SmartResult

    rings = [{"inner_px": a, "outer_px": b, "mean_c": 90.0 - a, "max_c": 95.0 - a,
              "min_c": 85.0 - a} for a, b in ((0, 5), (5, 10), (10, 25))]
    if not valid:
        r = SmartResult("searching", False, sample={"mean_c": None, "max_c": None,
                                                     "min_c": None},
                        rings=[{**g, "mean_c": None, "max_c": None, "min_c": None}
                               for g in rings])
    else:
        r = SmartResult(state, True, bbox=(10, 10, 20, 20),  # type: ignore[arg-type]
                        labels=np.ones((10, 10), dtype=np.uint8),
                        sample={"mean_c": 120.0, "max_c": 130.0, "min_c": 110.0}, rings=rings,
                        dims={"area_px": 100, "units": "px"}, edge_level_c=70.0)
    r.frame_ts_ns = 1_000_000_000  # tracked on the reported frame (see _live)
    return r


def _live(rois, smart):  # type: ignore[no-untyped-def]
    return live_roi_payload(counts=_counts_for(25.0), ir_format=IRFMT, rois=rois, acquiring=True,
                            frame_id=1, host_ts_ns=1_000_000_000, now_ns=1_010_000_000,
                            smart=smart)


def test_feed_smart_entry_shape() -> None:
    p = _live([SMART], {7: _smart_result("holding")})
    (roi,) = p["rois"]
    assert roi["id"] == 7 and roi["name"] == "sample" and roi["kind"] == "smart"
    assert roi["valid"] is True and roi["state"] == "holding"
    assert roi["mean_c"] == 120.0 and roi["max_c"] == 130.0 and roi["min_c"] == 110.0
    assert roi["value_c"] is None and roi["over_range"] is False
    assert len(roi["rings"]) == 3 and roi["rings"][0]["inner_px"] == 0
    assert roi["dims"]["units"] == "px"


def test_feed_smart_searching_invalid() -> None:
    p = _live([SMART], {7: _smart_result(valid=False)})
    (roi,) = p["rois"]
    assert roi["valid"] is False and roi["state"] == "searching"
    assert roi["mean_c"] is None and roi["max_c"] is None and roi["dims"] is None


def test_feed_smart_without_result_is_invalid() -> None:
    (roi,) = _live([SMART], {})["rois"]
    assert roi["valid"] is False and roi["state"] == "searching" and roi["mean_c"] is None


def test_feed_smart_stale_frame_is_invalid() -> None:
    p = live_roi_payload(counts=_counts_for(25.0), ir_format=IRFMT, rois=[SMART], acquiring=True,
                         frame_id=1, host_ts_ns=1_000_000_000, now_ns=5_000_000_000,
                         smart={7: _smart_result("locked")})
    (roi,) = p["rois"]
    assert roi["valid"] is False and roi["mean_c"] is None


def test_feed_smart_valid_but_no_temps_is_invalid() -> None:
    # no false-green: a "valid" result without a sample temperature must not reach the controller
    r = _smart_result("locked")
    r.sample = {"mean_c": None, "max_c": None, "min_c": None}
    (roi,) = _live([SMART], {7: r})["rois"]
    assert roi["valid"] is False


def test_bad_smart_roi_only_invalidates_itself() -> None:
    bad = {"id": 8, "name": "broken", "kind": "smart", "search": [[0, 0], [1, 1], [2, 2]]}
    weird = _smart_result("locked")
    weird.rings = None  # type: ignore[assignment]  # a malformed result must not crash the feed
    p = _live([bad, CIRCLE, {**SMART, "id": 9}], {8: _smart_result(valid=False), 9: weird})
    by_id = {r["id"]: r for r in p["rois"]}
    assert by_id[10]["valid"] is True and abs(by_id[10]["mean_c"] - 25.0) < 0.05
    assert by_id[8]["valid"] is False and by_id[8]["name"] == "broken"
    assert by_id[9]["valid"] is False and by_id[9]["mean_c"] is None


def test_feed_smart_unstamped_result_is_invalid() -> None:
    # a result that cannot say which frame it measured is unknown, never healthy
    r = _smart_result("locked")
    r.frame_ts_ns = None
    (roi,) = _live([SMART], {7: r})["rois"]
    assert roi["valid"] is False and roi["mean_c"] is None


def test_feed_smart_result_older_than_frame_is_invalid() -> None:
    from flir_research_interface.analysis.live_temps import SMART_LAG_MS

    r = _smart_result("locked")
    r.frame_ts_ns = 1_000_000_000 - int((SMART_LAG_MS + 1) * 1e6)  # the tracker fell behind
    (roi,) = _live([SMART], {7: r})["rois"]
    assert roi["valid"] is False and roi["mean_c"] is None
    r.frame_ts_ns = 1_000_000_000 - int((SMART_LAG_MS - 1) * 1e6)  # within one frame: still ok
    (roi,) = _live([SMART], {7: r})["rois"]
    assert roi["valid"] is True
