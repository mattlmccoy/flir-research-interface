"""Real-run acceptance for the smart ROI tracker (skipped unless ``FRI_REAL_RUN`` is set).

Read-only on the run: the store is written to ``tmp_path`` via ``out_dir``."""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pytest

from flir_research_interface.analysis.smart_roi import parse_smart_roi
from flir_research_interface.analysis.smart_series import (
    STATE_CODES,
    compute_smart_series,
    load_smart_series,
)
from flir_research_interface.playback.reader import ExperimentReader

REAL_RUN = os.environ.get("FRI_REAL_RUN")
pytestmark = pytest.mark.skipif(not REAL_RUN, reason="set FRI_REAL_RUN to a recorded run dir")


def _at(t_s: np.ndarray, t: float) -> int:
    return int(np.argmin(np.abs(t_s - t)))


def test_real_run_tracks_sample(tmp_path: Path) -> None:
    assert REAL_RUN
    reader = ExperimentReader(Path(REAL_RUN))
    outline = next(r for r in reader.metadata["rois"] if r.get("name") == "freehand_sample")
    spec = parse_smart_roi({"id": outline["id"], "kind": "smart", "name": "sample",
                            "search": outline["points"]})
    t0 = time.perf_counter()
    compute_smart_series(reader, spec, out_dir=tmp_path)
    wall = time.perf_counter() - t0
    s = load_smart_series(tmp_path, spec.id)
    assert s is not None
    state, t_s, area = s["state"], s["t_s"], s["area_px"]
    n_state = {k: int((state == c).sum()) for k, c in STATE_CODES.items()}
    i274, i604 = _at(t_s, 274.0), _at(t_s, 604.0)
    print(f"\nwall={wall:.1f}s frames={len(state)} states={n_state} "
          f"area@274s={area[i274]:.0f} area@604s={area[i604]:.0f}")

    assert state[0] == STATE_CODES["searching"]
    win = (t_s >= 60.0) & (t_s <= 540.0)
    assert win.any()
    assert (state[win] == STATE_CODES["locked"]).mean() >= 0.90
    assert area[i604] < area[i274]
