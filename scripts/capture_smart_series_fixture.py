"""Capture the frontend's smart ROI fixtures from the real backend code (never PySpin).

Both fixtures come from the five real A70 frames in
``backend/tests/fixtures/smart_roi_20261020.npz`` (graphite/PA12 cube, run 20261020_144402_Run).

* series: builds a short recording, computes the smart ROI with the real job route and saves the
  real ``GET .../smart-roi/{id}`` payload to
  ``frontend/src/lib/fixtures/smart_series_20261020.json``.
  Frame order (33 ms apart): t=0 s (cold start), 55 s ×3, 274 s, 549 s, then 40 frames of uniform
  25 °C (the sample disappears: holding for HOLD_S, then searching), then 604 s ×2 (re-lock).
* feed: steps the real live tracker (``SmartLive.on_frame``) over the same frames and saves the
  real ``live_roi_payload`` (``GET /api/live/roi-temps``) at the 549 s frame (locked), the first
  cold frame after it (holding) and the first frame after the hold lapses (searching) to
  ``frontend/src/lib/fixtures/smart_feed_20261020.json``.

Run from ``backend/``:
``uv run --no-sync python ../scripts/capture_smart_series_fixture.py [--only series|feed]``
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from flir_research_interface.acquisition.smart_live import SmartLive
from flir_research_interface.analysis.live_temps import live_roi_payload
from flir_research_interface.analysis.smart_roi import HOLD_S
from flir_research_interface.api.app import create_app
from flir_research_interface.camera.base import Frame
from flir_research_interface.recording.recorder import Recorder

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend/tests/fixtures/smart_roi_20261020.npz"
OUT = ROOT / "frontend/src/lib/fixtures/smart_series_20261020.json"
FEED_OUT = ROOT / "frontend/src/lib/fixtures/smart_feed_20261020.json"
FMT = "TemperatureLinear10mK"


def _frames() -> tuple[list[np.ndarray], list[list[int]]]:
    """The real frame sequence (see module docstring) and the drawn polygon in crop pixels."""
    z = np.load(SRC)
    real = z["celsius"].astype(np.float64)
    ox, oy = (int(v) for v in z["origin"])
    poly = [[int(x) - ox, int(y) - oy] for x, y in z["polygon"]]
    cold = np.full_like(real[0], 25.0)
    return [real[0], *([real[1]] * 3), real[2], real[3], *([cold] * 40), real[4], real[4]], poly


def _counts(c: np.ndarray) -> np.ndarray:
    return np.round((c + 273.15) * 100.0).astype(np.uint16)


def capture_feed() -> None:
    """Real ``live_roi_payload`` payloads: locked at the 549 s frame (index 5), then the first
    holding and the first searching frame after it."""
    frames, poly = _frames()
    smart = {"id": 3, "kind": "smart", "name": "graphite", "search": poly}
    live = SmartLive()
    live.set_rois([smart])
    got: dict[str, dict[str, object]] = {}
    for i, c in enumerate(frames):
        ts = 5_000_000_000 + i * 33_000_000
        counts = _counts(c)
        live.on_frame(Frame(
            frame_id=100 + i, device_timestamp_ns=ts, host_timestamp_ns=ts,
            pixel_format="Mono16", ir_format=FMT, counts=counts, incomplete=False,
        ))
        p = live_roi_payload(
            counts=counts, ir_format=FMT, rois=[smart], acquiring=True, frame_id=100 + i,
            host_ts_ns=ts, now_ns=ts + 10_000_000, smart=live.latest(),
        )
        state = str(p["rois"][0]["state"])
        if state not in got and i >= 5:  # from the 549 s frame on (index 0 is a cold start)
            p["_frame"] = {"index": i, "t_ms": i * 33}
            got[state] = p
    missing = {"locked", "holding", "searching"} - got.keys()
    if missing:
        raise SystemExit(f"feed capture never reached {sorted(missing)}")
    out = {
        **got,
        "_capture": {
            "source": "backend/tests/fixtures/smart_roi_20261020.npz via"
            " scripts/capture_smart_series_fixture.py --only feed (SmartLive + live_roi_payload)",
            "hold_s": HOLD_S,
        },
    }
    FEED_OUT.parent.mkdir(exist_ok=True)
    FEED_OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(FEED_OUT, {k: v["_frame"] for k, v in got.items()})


def capture_series() -> None:
    frames, poly = _frames()
    with tempfile.TemporaryDirectory() as tmp:
        rec = Recorder(None, experiments_root=Path(tmp), chunk_frames=8)
        smart = {"id": 3, "kind": "smart", "name": "graphite", "search": poly}
        d = rec.start(
            name="smart_fixture", metadata={},
            camera_info={
                "backend": "simulated", "ir_format": "TemperatureLinear10mK", "model": "Sim",
            },
            extra={"rois": [smart]},
        )
        for i, c in enumerate(frames):
            rec.submit(Frame(
                frame_id=100 + i, device_timestamp_ns=1_000_000_000 + i * 33_000_000,
                host_timestamp_ns=5_000_000_000 + i * 33_000_000, pixel_format="Mono16",
                ir_format="TemperatureLinear10mK",
                counts=_counts(c), incomplete=False,
            ))
        rec.stop()
        app = create_app(default_backend="simulated", experiments_root=Path(tmp), min_free_gb=0.0)
        with TestClient(app) as cl:
            base = f"/api/experiments/{d.name}/smart-roi/3"
            missing = cl.get(base)
            cl.post(f"{base}/compute").raise_for_status()
            while cl.get(f"{base}/status").json()["state"] == "running":
                time.sleep(0.05)
            body = cl.get(base).json()
    body["_capture"] = {
        "source": "backend/tests/fixtures/smart_roi_20261020.npz"
        " via scripts/capture_smart_series_fixture.py",
        "missing_status": missing.status_code, "missing_body": missing.json(),
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(body, indent=1) + "\n")
    print(OUT, len(body["state"]), "rows;", {s: body["state"].count(s) for s in set(body["state"])})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", choices=("series", "feed"), default=None)
    only = ap.parse_args().only
    if only in (None, "series"):
        capture_series()
    if only in (None, "feed"):
        capture_feed()


if __name__ == "__main__":
    main()
