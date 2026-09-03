"""Frame-range export (ResearchIR Export dialog): a range/step of frames as a zip of per-frame
CSV or TIFF files, or as a multi-page TIFF stack, written under exports/."""

from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.camera.base import Frame
from flir_research_interface.recording.recorder import Recorder


def _exp(root: Path) -> str:
    rec = Recorder(None, experiments_root=root, chunk_frames=4, min_free_gb=0.0)
    d = rec.start(name="fr", metadata={}, camera_info={"ir_format": "TemperatureLinear10mK"})
    for i in range(10):
        rec.submit(
            Frame(
                frame_id=i,
                device_timestamp_ns=i * 33_000_000,
                host_timestamp_ns=i,
                pixel_format="Mono16",
                ir_format="TemperatureLinear10mK",
                counts=np.full((4, 6), 30000 + i, np.uint16),
                incomplete=False,
            )
        )
    rec.stop()
    return d.name


def test_frame_range_zip_of_csv_and_tiff_stack(tmp_path: Path) -> None:
    name = _exp(tmp_path)
    with TestClient(create_app(experiments_root=tmp_path)) as c:
        r = c.post(
            f"/api/experiments/{name}/export/frames",
            json={"start": 2, "stop": 9, "step": 3, "format": "csv"},
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["frames"] == [2, 5, 8] and j["path"].endswith("frames_0002-0008_step3_csv.zip")
        with zipfile.ZipFile(j["path"]) as z:
            names = sorted(z.namelist())
            assert names == ["frame_0002.csv", "frame_0005.csv", "frame_0008.csv"]
            first = z.read("frame_0002.csv").decode().splitlines()
            assert len(first) >= 4 and "26.87" in first[-1]  # 30002 counts → 26.87 °C
        r = c.post(
            f"/api/experiments/{name}/export/frames",
            json={"start": 0, "stop": 10, "step": 5, "format": "tiff-stack"},
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["path"].endswith(".tif") and j["frames"] == [0, 5]
        from PIL import Image

        im = Image.open(j["path"])
        assert getattr(im, "n_frames", 1) == 2 and im.mode == "F"
        assert (
            c.post(
                f"/api/experiments/{name}/export/frames",
                json={"start": 5, "stop": 2, "step": 1, "format": "csv"},
            ).status_code
            == 400
        )
        assert (
            c.post(
                f"/api/experiments/{name}/export/frames",
                json={"start": 0, "stop": 2, "step": 1, "format": "bmp"},
            ).status_code
            == 400
        )
