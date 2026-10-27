"""Capture the real over-range smart ROI fixture from run 20261020_144402_Run (read-only).

Near t = 626 s the graphite cube exceeded the A70's -20..250 °C case: a few sample pixels wrapped
(counts ~19 300, i.e. about -80 °C) and ``over_range_mask`` flags them. This script copies the raw
uint16 counts of five frames (clean lock frames before, three over-range frames, one after) cropped
to the stored smart series' bbox + 40 px, with the ROI's drawn polygon, frame indices, times and
the camera's active case ceiling, to ``backend/tests/fixtures/smart_overrange_20261020.npz``.

It only READS the run. Run from ``backend/``:
``.venv/bin/python ../scripts/capture_smart_overrange_fixture.py [RUN_DIR]``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.radiometry.overrange import over_range_mask

RUN = Path("/Volumes/FLIR SSD/FLIR-recordings/20261020_144402_Run")
ROI_ID = 113  # the run's smart_powder_sample ROI (rings 5/10/25 px, relative rule, 0.5)
INDICES = (18780, 18788, 18789, 18820, 18845, 18850)
MARGIN = 40
OUT = Path(__file__).resolve().parents[1] / "backend/tests/fixtures/smart_overrange_20261020.npz"


def main() -> None:
    run = Path(sys.argv[1]) if len(sys.argv) > 1 else RUN
    reader = ExperimentReader(run)
    spec = json.loads((run / "smart_roi" / f"{ROI_ID}.spec.json").read_text())["spec"]
    with np.load(run / "smart_roi" / f"{ROI_ID}.npz", allow_pickle=False) as z:
        bbox = z["bbox"][list(INDICES)]
    x0 = max(0, int(bbox[:, 0].min()) - MARGIN)
    y0 = max(0, int(bbox[:, 1].min()) - MARGIN)
    frames = [reader.counts_block(i, i + 1)[0] for i in INDICES]
    h, w = frames[0].shape
    x1 = min(w, int(bbox[:, 2].max()) + MARGIN)
    y1 = min(h, int(bbox[:, 3].max()) + MARGIN)
    counts = np.stack([f[y0:y1, x0:x1] for f in frames]).astype(np.uint16)
    for i, f in zip(INDICES, frames, strict=True):
        m = over_range_mask(f)
        n = 0 if m is None else int(m.sum())
        inside = 0 if m is None else int(m[y0:y1, x0:x1].sum())
        print(f"frame {i}: t={reader.t_s(i):.3f}s over px={n} (in crop {inside})")
    case = (reader.metadata.get("camera") or {}).get("active_case") or {}
    np.savez_compressed(
        OUT,
        counts=counts,
        origin=np.array([x0, y0], dtype=np.int64),
        frame_shape=np.array([h, w], dtype=np.int64),
        polygon=np.array(spec["search"], dtype=np.int32),
        rings_px=np.array(spec["rings_px"], dtype=np.int64),
        indices=np.array(INDICES, dtype=np.int64),
        t_s=np.array([reader.t_s(i) for i in INDICES], dtype=np.float64),
        high_c=np.float64(case["high_c"]),
        ir_format=np.array(reader.ir_format or ""),
    )
    print(OUT, counts.shape, "origin", (x0, y0), "case high_c", case["high_c"])


if __name__ == "__main__":
    main()
