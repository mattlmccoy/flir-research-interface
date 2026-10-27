"""Backend over-range detection mirrors the frontend: saturated, and wrapped (implausibly cold)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from flir_research_interface.radiometry.overrange import SAT_HI, over_range_mask

FIXTURE = Path(__file__).parent / "fixtures" / "smart_overrange_20261020.npz"


def test_normal_frame_has_none() -> None:
    assert over_range_mask(np.full((8, 8), 29500, np.uint16), kelvin_per_count=0.01) is None


def test_saturated_flagged() -> None:
    c = np.full((8, 8), 29500, np.uint16)
    c[2, 2] = SAT_HI + 100
    m = over_range_mask(c, kelvin_per_count=0.01)
    assert m is not None and m[2, 2] and int(m.sum()) == 1


def test_hot_frame_wrap_flagged() -> None:
    c = np.full((8, 8), 30000, np.uint16)
    c[0, 0] = 52000  # frame is hot
    c[3, 3] = 19000  # wrapped, reads ~ -84 C
    m = over_range_mask(c, kelvin_per_count=0.01)
    assert m is not None and m[3, 3]


def test_sub_floor_pixel_flagged_even_in_a_cool_frame() -> None:
    # A small hot spot (an arc) can wrap while nothing else in the frame reaches ~177 C. Below
    # -13 C never happens in this lab: 88,771 real frames (runs 20261026_164401, 20261027_145342)
    # had no pixel <= 26000 counts unless the frame was also hot, so flagging costs nothing real
    # and an unflagged wrap would read as -80 C to TC-POWER's over-temperature guard.
    c = np.full((8, 8), 30000, np.uint16)
    c[3, 3] = 19000
    m = over_range_mask(c, kelvin_per_count=0.01)
    assert m is not None and m[3, 3] and int(m.sum()) == 1


def test_real_wrapped_spot_flagged_when_its_surroundings_are_below_177c() -> None:
    # Real wrapped frame (run 20261020_144402_Run, frame 18820: 6 sample pixels wrapped to
    # ~-80 C). Derived case: every pixel >= 45000 counts (~177 C) is lowered to 44000, so the
    # frame no longer looks "hot" -- the wrapped pixels themselves are untouched.
    d = np.load(FIXTURE)
    k = int(np.flatnonzero(d["indices"] == 18820)[0])
    frame = d["counts"][k].copy()
    wrapped = frame <= 26000
    assert int(wrapped.sum()) >= 6  # the real wrapped pixels are there
    frame[frame >= 45000] = 44000
    assert int(frame.max()) < 45000
    m = over_range_mask(frame, kelvin_per_count=0.01)
    assert m is not None and bool(m[wrapped].all())


def test_100mk_frame_is_judged_in_its_own_units() -> None:
    # TemperatureLinear100mK (0.1 K/count; the A70's high case): 40 C is ~3131 counts. The
    # -13 C floor must be applied in that format's counts, not 10 mK counts.
    c = np.full((8, 8), round((40.0 + 273.15) / 0.1), np.uint16)
    assert over_range_mask(c, kelvin_per_count=0.1) is None
    c[3, 3] = round((-80.0 + 273.15) / 0.1)  # a wrapped reading in 100 mK
    m = over_range_mask(c, kelvin_per_count=0.1)
    assert m is not None and m[3, 3] and int(m.sum()) == 1
