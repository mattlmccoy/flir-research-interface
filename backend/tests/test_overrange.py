"""Backend over-range detection mirrors the frontend: saturated + hot-frame wrap, cold-safe."""

from __future__ import annotations

import numpy as np

from flir_research_interface.radiometry.overrange import SAT_HI, over_range_mask


def test_normal_frame_has_none() -> None:
    assert over_range_mask(np.full((8, 8), 29500, np.uint16)) is None


def test_saturated_flagged() -> None:
    c = np.full((8, 8), 29500, np.uint16)
    c[2, 2] = SAT_HI + 100
    m = over_range_mask(c)
    assert m is not None and m[2, 2] and int(m.sum()) == 1


def test_hot_frame_wrap_flagged() -> None:
    c = np.full((8, 8), 30000, np.uint16)
    c[0, 0] = 52000  # frame is hot
    c[3, 3] = 19000  # wrapped, reads ~ -84 C
    m = over_range_mask(c)
    assert m is not None and m[3, 3]


def test_cold_scene_untouched() -> None:
    c = np.full((8, 8), 30000, np.uint16)
    c[3, 3] = 19000  # lone cold/dead pixel, frame not hot
    assert over_range_mask(c) is None
