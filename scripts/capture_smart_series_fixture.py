"""Capture the frontend's smart ROI series fixture from the real API (never PySpin).

Builds a short recording from the five real A70 frames in
``backend/tests/fixtures/smart_roi_20261020.npz`` (graphite/PA12 cube, run 20261020_144402_Run),
computes the smart ROI with the real job route and saves the real ``GET .../smart-roi/{id}``
payload to ``frontend/src/lib/fixtures/smart_series_20261020.json``.

Frame order (33 ms apart): t=0 s (cold start), 55 s ×3, 274 s, 549 s, then 40 frames of uniform
25 °C (the sample disappears: holding for HOLD_S, then searching), then 604 s ×2 (re-lock).

Run from ``backend/``: ``uv run --no-sync python ../scripts/capture_smart_series_fixture.py``
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.camera.base import Frame
from flir_research_interface.recording.recorder import Recorder

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend/tests/fixtures/smart_roi_20261020.npz"
OUT = ROOT / "frontend/src/lib/fixtures/smart_series_20261020.json"


def main() -> None:
    z = np.load(SRC)
    real = z["celsius"].astype(np.float64)
    ox, oy = (int(v) for v in z["origin"])
    poly = [[int(x) - ox, int(y) - oy] for x, y in z["polygon"]]
    cold = np.full_like(real[0], 25.0)
    frames = [real[0], *([real[1]] * 3), real[2], real[3], *([cold] * 40), real[4], real[4]]
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
                counts=np.round((c + 273.15) * 100.0).astype(np.uint16), incomplete=False,
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


if __name__ == "__main__":
    main()
