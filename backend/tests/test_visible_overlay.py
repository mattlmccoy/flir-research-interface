"""Visible-camera overlay alignment for media export."""

from __future__ import annotations

import numpy as np

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
