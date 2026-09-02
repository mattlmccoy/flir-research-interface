"""Camera housekeeping around a recording: device (FPA/housing) temperature at start and stop,
so a NUC-drift or a warm-up trend can be explained after the fact."""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app


def test_device_temperature_is_stamped_at_start_and_stop(tmp_path: Path) -> None:
    app = create_app(
        default_backend="simulated", sim_fps=60.0, experiments_root=tmp_path, min_free_gb=0.0
    )
    with TestClient(app) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        d = Path(
            c.post("/api/recording/start", json={"name": "temp", "nuc_hold": False}).json()[
                "experiment_dir"
            ]
        )
        meta = json.loads((d / "metadata.json").read_text())
        assert isinstance(meta["camera"]["device_temperature_c"], float)
        time.sleep(0.2)
        c.post("/api/recording/stop")
        ev = json.loads((d / "events.json").read_text())
        stop = next(e for e in ev if e["type"] == "camera_state")
        assert stop["when"] == "stop" and isinstance(stop["device_temperature_c"], float)
        c.post("/api/camera/disconnect")
