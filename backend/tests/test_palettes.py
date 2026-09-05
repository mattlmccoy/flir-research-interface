"""Export/media color palettes."""

from __future__ import annotations

import numpy as np

from flir_research_interface.analysis.palettes import PALETTE_NAMES, apply_lut, palette_lut


def test_every_named_palette_is_a_256x3_lut() -> None:
    for name in PALETTE_NAMES:
        lut = palette_lut(name)
        assert lut.shape == (256, 3) and lut.dtype == np.uint8


def test_palettes_differ_and_unknown_falls_back_to_inferno() -> None:
    assert not np.array_equal(palette_lut("iron"), palette_lut("viridis"))
    assert np.array_equal(palette_lut("nonsense"), palette_lut("inferno"))
    # grayscale is a straight black→white ramp
    g = palette_lut("grayscale")
    assert tuple(g[0]) == (0, 0, 0) and tuple(g[255]) == (255, 255, 255)


def test_apply_lut_maps_range_ends() -> None:
    lut = palette_lut("grayscale")
    out = apply_lut(np.array([[0.0, 100.0]], dtype=np.float32), 0.0, 100.0, lut)
    assert tuple(out[0, 0]) == (0, 0, 0) and tuple(out[0, 1]) == (255, 255, 255)
