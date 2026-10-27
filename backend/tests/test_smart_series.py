"""Smart ROI over a recorded run: full-rate job, stored per frame INDEX (Task 5)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from smart_recording import SMART, H, W, make_smart_run

from flir_research_interface.analysis.smart_roi import SmartTracker, parse_smart_roi
from flir_research_interface.analysis.smart_series import (
    STATE_CODES,
    compute_smart_series,
    load_smart_series,
)
from flir_research_interface.analysis.smart_wire import encode_labels
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.radiometry.overrange import over_range_mask
from flir_research_interface.radiometry.temperature_linear import (
    IRFormat,
    counts_to_celsius,
    kelvin_per_count,
)


def _same(a: float | None, b: float) -> bool:
    return (a is None and math.isnan(b)) or (a is not None and math.isclose(a, b))


def test_job_matches_stepwise_tracker(tmp_path: Path) -> None:
    reader = ExperimentReader(make_smart_run(tmp_path, n=8))
    spec = parse_smart_roi(SMART)
    progress: list[tuple[int, int]] = []
    path = compute_smart_series(reader, spec, lambda d, t: progress.append((d, t)))
    assert path == reader.path / "smart_roi" / "7.npz" and path.is_file()
    assert (reader.path / "smart_roi" / "7.spec.json").is_file()
    assert progress[-1] == (8, 8)

    s = load_smart_series(reader.path, 7)
    assert s is not None and len(s["state"]) == 8
    ref = SmartTracker(spec, W, H, cam=reader.metadata["camera"], optics=SMART)
    fmt = IRFormat(reader.ir_format or "")
    states = []
    for i in range(reader.n_frames):
        counts = reader.frame(i).counts
        r = ref.update(counts_to_celsius(counts, fmt), reader.t_s(i),
                       over_range_mask(counts, kelvin_per_count=kelvin_per_count(fmt)))
        states.append(r.state)
        assert s["state"][i] == STATE_CODES[r.state]
        assert bool(s["valid"][i]) is r.valid
        assert math.isclose(s["t_s"][i], reader.t_s(i))
        assert list(s["bbox"][i]) == (list(r.bbox) if r.bbox else [-1, -1, -1, -1])
        assert s["labels"][i] == (encode_labels(r.labels) if r.labels is not None else None)
        for k in ("mean", "max", "min"):
            assert _same(r.sample[f"{k}_c"], s[f"sample_{k}"][i])
            for j, ring in enumerate(r.rings):
                assert _same(ring[f"{k}_c"], s[f"ring_{k}"][i, j])
        for key in ("area_px", "length_px", "width_px", "area_change_pct", "centroid_x"):
            want = r.dims[key] if r.dims else None
            assert _same(want, s[key][i])
    assert states[0] == "searching" and "locked" in states  # the run exercises both states
    assert s["rings_px"] == [5, 10, 25]


def test_series_indexed_by_frame_index_with_wrapped_ids(tmp_path: Path) -> None:
    d = make_smart_run(tmp_path, frame_ids=[65534, 65535, 1, 2], cold_frames=())
    reader = ExperimentReader(d)
    compute_smart_series(reader, parse_smart_roi(SMART))
    s = load_smart_series(d, 7)
    assert s is not None
    assert len(s["state"]) == 4  # every frame index, in recorded order, despite the id wrap
    assert np.all(np.diff(s["t_s"]) > 0)
    assert list(s["state"]) == [STATE_CODES["locked"]] * 4
    assert np.all(np.diff(s["area_px"]) > 0)  # growing blob: rows follow recording order


def test_load_missing_is_none(tmp_path: Path) -> None:
    assert load_smart_series(tmp_path, 3) is None


def test_out_dir_redirects_store_and_leaves_run_untouched(tmp_path: Path) -> None:
    run = make_smart_run(tmp_path / "run", n=4)
    reader = ExperimentReader(run)
    out = tmp_path / "out"
    out.mkdir()
    path = compute_smart_series(reader, parse_smart_roi(SMART), out_dir=out)
    assert path == out / "smart_roi" / "7.npz" and path.is_file()
    assert (out / "smart_roi" / "7.spec.json").is_file()
    assert not (run / "smart_roi").exists()
    s = load_smart_series(out, 7)
    assert s is not None and len(s["state"]) == 4
