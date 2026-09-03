"""Milestone 7 exports: ROI series CSV, single-frame CSV/TIFF/PNG/NPY, whole-recording HDF5."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

import h5py
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from flir_research_interface.analysis.export import (
    export_hdf5,
    frame_bytes,
    series_csv,
)
from flir_research_interface.api.app import create_app
from flir_research_interface.camera.base import Frame
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.recording.recorder import Recorder

W, H = 8, 6


def _make_experiment(root: Path, n: int = 5, name: str = "exp") -> Path:
    rec = Recorder(None, experiments_root=root, chunk_frames=4)
    d = rec.start(
        name=name,
        metadata={"material": "PA12"},
        camera_info={"backend": "simulated", "ir_format": "TemperatureLinear10mK", "model": "Sim"},
    )
    for i in range(n):
        counts = np.full((H, W), 29815, dtype=np.uint16)  # 25.00 °C
        counts[1:3, 2:4] = 29815 + 100 * (i + 1)  # 26, 27, … °C hot block
        rec.submit(
            Frame(
                frame_id=100 + i,
                device_timestamp_ns=1_000_000_000 + i * 100_000_000,
                host_timestamp_ns=5_000_000_000 + i * 100_000_000,
                pixel_format="Mono16",
                ir_format="TemperatureLinear10mK",
                counts=counts,
                incomplete=False,
            )
        )
    rec.stop()
    return d


ROIS = [
    {"id": 1, "kind": "spot", "x": 2, "y": 1},
    {"id": 2, "kind": "rect", "x0": 1, "y0": 0, "x1": 5, "y1": 4},
]


def test_series_csv_has_header_comments_and_one_row_per_frame(tmp_path: Path) -> None:
    r = ExperimentReader(_make_experiment(tmp_path, n=5))
    text = series_csv(r, ROIS)
    lines = text.splitlines()
    comments = [ln for ln in lines if ln.startswith("#")]
    assert any("units: celsius" in c for c in comments)
    assert any("S1" in c and "x=2" in c for c in comments)
    assert any("R2" in c and "x0=1" in c for c in comments)
    rows = list(csv.reader(ln for ln in lines if not ln.startswith("#")))
    assert rows[0] == [
        "t_s",
        "frame_id",
        "S1_value",
        "R2_mean",
        "R2_min",
        "R2_max",
        "R2_std",
        "R2_n",
    ]
    assert len(rows) == 1 + 5
    assert float(rows[1][2]) == pytest.approx(26.0, abs=1e-3)
    assert float(rows[5][5]) == pytest.approx(30.0, abs=1e-3)
    assert rows[1][1] == "100"


def test_frame_csv_is_a_celsius_grid(tmp_path: Path) -> None:
    r = ExperimentReader(_make_experiment(tmp_path, n=2))
    data, media_type, filename = frame_bytes(r, 1, "csv")
    assert media_type == "text/csv" and filename.endswith("_frame0001.csv")
    rows = [ln for ln in data.decode().splitlines() if not ln.startswith("#")]
    grid = np.array([[float(v) for v in row.split(",")] for row in rows])
    assert grid.shape == (H, W)
    assert grid[1, 2] == pytest.approx(27.0, abs=1e-3)
    assert grid[0, 0] == pytest.approx(25.0, abs=1e-3)


def test_frame_tiff_is_float32_celsius(tmp_path: Path) -> None:
    r = ExperimentReader(_make_experiment(tmp_path, n=1))
    data, media_type, _ = frame_bytes(r, 0, "tiff")
    assert media_type == "image/tiff"
    img = Image.open(io.BytesIO(data))
    assert img.mode == "F"
    arr = np.asarray(img)
    assert arr.dtype == np.float32 and arr.shape == (H, W)
    assert arr[1, 2] == pytest.approx(26.0, abs=1e-3)


def test_frame_png_is_16bit_raw_counts(tmp_path: Path) -> None:
    r = ExperimentReader(_make_experiment(tmp_path, n=1))
    data, media_type, _ = frame_bytes(r, 0, "png")
    assert media_type == "image/png"
    arr = np.asarray(Image.open(io.BytesIO(data)))
    assert arr.dtype == np.uint16 and arr.shape == (H, W)
    assert int(arr[1, 2]) == 29915 and int(arr[0, 0]) == 29815


def test_frame_npy_roundtrips_counts(tmp_path: Path) -> None:
    r = ExperimentReader(_make_experiment(tmp_path, n=1))
    data, media_type, _ = frame_bytes(r, 0, "npy")
    assert media_type == "application/octet-stream"
    arr = np.load(io.BytesIO(data))
    assert arr.dtype == np.uint16 and int(arr[1, 2]) == 29915


def test_frame_bytes_rejects_unknown_format_and_bad_index(tmp_path: Path) -> None:
    r = ExperimentReader(_make_experiment(tmp_path, n=1))
    with pytest.raises(ValueError):
        frame_bytes(r, 0, "bmp")
    with pytest.raises(IndexError):
        frame_bytes(r, 5, "csv")


def test_export_hdf5_contains_counts_time_and_conversion(tmp_path: Path) -> None:
    d = _make_experiment(tmp_path, n=5)
    r = ExperimentReader(d)
    result = export_hdf5(r)
    out = Path(result["path"])
    assert out.parent == d / "exports" and out.suffix == ".h5"
    assert result["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert result["size_bytes"] == out.stat().st_size
    with h5py.File(out, "r") as f:
        counts = f["counts"]
        assert counts.shape == (5, H, W) and counts.dtype == np.uint16
        assert int(counts[2, 1, 2]) == 29815 + 300
        assert f["t_s"].shape == (5,)
        assert f["frame_id"][0] == 100
        assert f["device_timestamp_ns"][1] == 1_100_000_000
        assert f.attrs["ir_format"] == "TemperatureLinear10mK"
        assert f.attrs["kelvin_per_count"] == pytest.approx(0.01)
        assert f.attrs["kelvin_offset"] == pytest.approx(273.15)
        assert json.loads(f.attrs["metadata_json"])["experiment"]["material"] == "PA12"
        assert "celsius = counts * kelvin_per_count - kelvin_offset" in f.attrs["conversion"]
    # the canonical store is untouched: re-exporting overwrites the same file deterministically
    again = export_hdf5(r)
    assert again["path"] == result["path"]


def test_export_endpoints(tmp_path: Path) -> None:
    d = _make_experiment(tmp_path, n=3, name="run1")
    app = create_app(default_backend="simulated", experiments_root=tmp_path)
    with TestClient(app) as c:
        rois = json.dumps(ROIS)
        res = c.get(f"/api/experiments/{d.name}/export/series.csv", params={"rois": rois})
        assert res.status_code == 200, res.text
        assert res.headers["content-type"].startswith("text/csv")
        assert "attachment" in res.headers["content-disposition"]
        assert "S1_value" in res.text
        bad = c.get(f"/api/experiments/{d.name}/export/series.csv", params={"rois": "x"})
        assert bad.status_code == 400

        fr = c.get(f"/api/experiments/{d.name}/frames/1/export", params={"format": "tiff"})
        assert fr.status_code == 200 and fr.headers["content-type"] == "image/tiff"
        gif = c.get(f"/api/experiments/{d.name}/frames/1/export", params={"format": "gif"})
        assert gif.status_code == 400
        far = c.get(f"/api/experiments/{d.name}/frames/99/export", params={"format": "csv"})
        assert far.status_code == 404

        h5 = c.post(f"/api/experiments/{d.name}/export/hdf5")
        assert h5.status_code == 200, h5.text
        body = h5.json()
        assert Path(body["path"]).is_file() and body["size_bytes"] > 0
        assert c.post("/api/experiments/nope/export/hdf5").status_code == 404
