"""Visible-camera overlay alignment for media export."""

from __future__ import annotations

import numpy as np
import pytest

from flir_research_interface.analysis.visible_overlay import blend_visible, ir_to_visible_coeffs

# The stored visible→IR homography (normalised) and one calibration pair from a real run.
_H = [[1.3745810579148645, -0.026240839260570817, -0.16781215289651508],
      [-0.020620321602787234, 1.3891426992372955, -0.1863323173289433],
      [-0.0428624558460813, -0.06595216450654162, 1.0]]
_IR_NORM = (0.3045267489711934, 0.11996336996336997)
_VIS_NORM = (0.34296875, 0.21979166666666666)


def _apply(coeffs, x, y):
    a, b, c, d, e, f, g, h = coeffs
    w = g * x + h * y + 1.0
    return (a * x + b * y + c) / w, (d * x + e * y + f) / w


def test_ir_to_visible_coeffs_maps_a_calibration_pair() -> None:
    out_w, out_h, vis_w, vis_h = 640, 480, 1280, 960
    coeffs = ir_to_visible_coeffs(_H, out_w, out_h, vis_w, vis_h)
    sx, sy = _apply(coeffs, _IR_NORM[0] * out_w, _IR_NORM[1] * out_h)
    # the IR pixel should map to (near) its paired visible pixel — a few px of fit error is fine
    assert abs(sx - _VIS_NORM[0] * vis_w) < 6
    assert abs(sy - _VIS_NORM[1] * vis_h) < 6


def test_blend_visible_opacity_bounds() -> None:
    body = np.zeros((4, 4, 3), dtype=np.uint8)
    warped = np.full((4, 4, 3), 200, dtype=np.uint8)
    assert np.array_equal(blend_visible(body, warped, 0.0), body)  # off = unchanged
    full = blend_visible(body, warped, 1.0)
    assert int(full[0, 0, 0]) == 200  # full opacity = the visible frame
    half = blend_visible(body, warped, 0.5)
    assert 95 <= int(half[0, 0, 0]) <= 105  # 50% blend


def test_segment_windows_map_thermal_time_through_each_segment_start() -> None:
    """Segments sit on the thermal axis at t_start_s (see playback.visible_timing)."""
    from flir_research_interface.analysis.visible_overlay import segment_windows

    timeline = [{"index": 0, "file": "visible.mp4", "t_start_s": 24.15, "duration_s": 231.9}]
    # thermal 30..40 s is video 5.85..15.85 s
    [(name, local, dur, g0)] = segment_windows(timeline, 30.0, 40.0)
    assert name == "visible.mp4" and dur == pytest.approx(10.0)
    assert local == pytest.approx(5.85) and g0 == pytest.approx(30.0)
    assert segment_windows(timeline, 0.0, 20.0) == []  # before the video starts: no frames


def test_segment_windows_split_across_a_stream_gap() -> None:
    """Run 20260923_175956: the stream dropped ~85 s in and reconnected into visible_001.mp4."""
    from flir_research_interface.analysis.visible_overlay import segment_windows

    timeline = [
        {"index": 0, "file": "visible.mp4", "t_start_s": 0.0, "duration_s": 77.0},
        {"index": 1, "file": "visible_001.mp4", "t_start_s": 95.0, "duration_s": 160.0},
    ]
    assert segment_windows(timeline, 70.0, 100.0) == [
        ("visible.mp4", 70.0, 7.0, 70.0),
        ("visible_001.mp4", pytest.approx(0.25), pytest.approx(4.75), pytest.approx(95.25)),
    ]
    assert segment_windows(timeline, 80.0, 90.0) == []  # entirely inside the gap
    # an unprobed segment runs until the next one starts (or forever for the last)
    timeline[1]["duration_s"] = None
    assert segment_windows(timeline, 300.0, 310.0) == [("visible_001.mp4", 205.0, 10.0, 300.0)]


def test_segment_windows_never_extract_the_torn_first_frame() -> None:
    """A window reaching a segment's start begins FRAME0_SKIP_S into the file."""
    from flir_research_interface.analysis.visible_overlay import segment_windows
    from flir_research_interface.playback.visible_timing import FRAME0_SKIP_S

    timeline = [{"index": 0, "file": "visible.mp4", "t_start_s": 4.0, "duration_s": 200.0}]
    [(_, local, dur, g0)] = segment_windows(timeline, 0.0, 10.0)
    assert local == pytest.approx(FRAME0_SKIP_S)
    assert g0 == pytest.approx(4.0 + FRAME0_SKIP_S)
    assert dur == pytest.approx(6.0 - FRAME0_SKIP_S)
