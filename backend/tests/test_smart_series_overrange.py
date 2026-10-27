"""Stored smart series: the over-range columns (bounded readings) and their plot payload."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from smart_recording import make_overrange_run

from flir_research_interface.analysis.smart_roi import SmartTracker, parse_smart_roi
from flir_research_interface.analysis.smart_series import (
    compute_smart_series,
    load_smart_series,
    series_payload,
)
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.radiometry.overrange import over_range_mask
from flir_research_interface.radiometry.temperature_linear import IRFormat, counts_to_celsius


def _same(a: float | None, b: float) -> bool:
    return (a is None and math.isnan(b)) or (a is not None and math.isclose(a, b))


def _computed(tmp_path: Path, **kw: float) -> tuple[ExperimentReader, dict]:  # type: ignore[type-arg]
    d, roi = make_overrange_run(tmp_path, **kw)
    reader = ExperimentReader(d)
    compute_smart_series(reader, parse_smart_roi(roi))
    s = load_smart_series(d, 113)
    assert s is not None
    return reader, s


def test_overrange_columns_match_the_tracker(tmp_path: Path) -> None:
    reader, s = _computed(tmp_path)
    spec = parse_smart_roi(next(r for r in reader.metadata["rois"] if r["id"] == 113))
    _, h, w = reader.counts_block(0, 1).shape
    ref = SmartTracker(spec, w, h, cam=reader.metadata["camera"])
    fmt = IRFormat(reader.ir_format or "")
    seen_over = 0
    for i in range(reader.n_frames):
        counts = reader.frame(i).counts
        r = ref.update(counts_to_celsius(counts, fmt), reader.t_s(i), over_range_mask(counts),
                       ceiling_c=250.00002441406252)
        o = r.over_stats
        if o is None:
            assert s["over_px"][i] == 0 and math.isnan(s["sample_mean_lb"][i])
            assert math.isnan(s["sample_min_over"][i])
            continue
        seen_over += 1
        assert s["over_px"][i] == o["sample"]["over_px"]
        assert _same(o["sample"]["mean_lb_c"], s["sample_mean_lb"][i])
        assert _same(o["sample"]["min_c"], s["sample_min_over"][i])
        assert bool(s["sample_min_is_bound"][i]) is o["sample"]["min_is_bound"]
        for q, g in enumerate(o["rings"]):
            assert s["ring_over_px"][i, q] == g["over_px"]
            if g["over_px"]:
                assert _same(g["mean_lb_c"], s["ring_mean_lb"][i, q])
    assert seen_over == 3  # the three real over-range frames
    assert list(s["over_px"]) == [0, 0, 1, 6, 2, 0]
    assert math.isclose(float(s["ceiling_c"][0]), 250.00002441406252)


def test_payload_over_block(tmp_path: Path) -> None:
    _, s = _computed(tmp_path)
    p = series_payload(s, 1000)
    assert p["over_range"] == [False, False, True, True, True, False]
    o = p["over"]
    assert o is not None and math.isclose(o["ceiling_c"], 250.00002441406252)
    assert o["sample"]["px"] == [0, 0, 1, 6, 2, 0]
    assert o["sample"]["mean_lb"][0] is None and o["sample"]["mean_lb"][3] is not None
    assert o["sample"]["min"][3] is not None and o["sample"]["min"][3] > 100.0
    assert o["sample"]["min_is_bound"][3] is False
    assert len(o["rings"]) == 3 and all(len(g["px"]) == 6 for g in o["rings"])
    # the feed-equivalent columns stay blank on those rows (unchanged behaviour)
    assert p["sample"]["mean"][3] is None and p["valid"][3] is False


def test_unknown_case_stores_nan_ceiling(tmp_path: Path) -> None:
    _, s = _computed(tmp_path / "unknown", high_c=float("nan"))
    _, known = _computed(tmp_path / "known")
    assert math.isnan(float(s["ceiling_c"][0]))
    assert series_payload(s, 1000)["over"]["ceiling_c"] is None
    # counted at the in-range max instead: still a bound, never above the one at the ceiling
    assert math.isfinite(s["sample_mean_lb"][3])
    assert s["sample_mean_lb"][3] <= known["sample_mean_lb"][3]


def test_old_series_without_over_columns_still_loads(tmp_path: Path) -> None:
    """A series computed before this change: no over columns. The payload says so (over None),
    keeps the stored over_range flags and never crashes."""
    _computed(tmp_path)
    path = next(tmp_path.glob("*/smart_roi/113.npz"))
    with np.load(path, allow_pickle=False) as z:
        old = {k: z[k] for k in z.files if not (
            k.endswith(("_mean_lb", "_min_over", "_min_is_bound", "over_px")) or k == "ceiling_c")}
    np.savez_compressed(path, allow_pickle=False, **old)
    s_old = load_smart_series(path.parent.parent, 113)
    assert s_old is not None
    p = series_payload(s_old, 1000)
    assert p["over"] is None
    assert p["over_range"] == [False, False, True, True, True, False]
