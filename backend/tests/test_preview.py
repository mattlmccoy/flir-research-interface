"""Preview/keyframe rendering: visualization-only PNGs derived from the store."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image

from flir_research_interface.analysis.preview import (
    IRON_LUT,
    generate_previews,
    render_keyframes,
    render_preview,
)
from flir_research_interface.camera.base import Frame
from flir_research_interface.recording.recorder import Recorder

W, H = 32, 24


def _exp(root: Path, n: int = 20, finalize: bool = True) -> Path:
    rec = Recorder(None, experiments_root=root, chunk_frames=8)
    d = rec.start(
        name="pv",
        metadata={},
        camera_info={"backend": "simulated", "ir_format": "TemperatureLinear10mK"},
    )
    for i in range(n):
        counts = np.full((H, W), 29815, dtype=np.uint16)
        counts[H // 2, W // 2] = 29815 + i * 500  # hotspot warming 5 K per frame
        rec.submit(
            Frame(
                frame_id=i,
                device_timestamp_ns=i * 33_000_000,
                host_timestamp_ns=i,
                pixel_format="Mono16",
                ir_format="TemperatureLinear10mK",
                counts=counts,
                incomplete=False,
            )
        )
    if finalize:
        rec.stop()
    else:
        rec.flush_for_test()
    return d


def _store_hash(path: Path) -> str:
    h = hashlib.sha256()
    for p in sorted((path / "thermal.zarr").rglob("*")):
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def test_iron_lut_shape_and_endpoints() -> None:
    assert IRON_LUT.shape == (256, 3) and IRON_LUT.dtype == np.uint8
    assert tuple(IRON_LUT[0]) == (0, 0, 0)
    assert IRON_LUT[255].min() > 200  # near white


def test_render_preview_is_rgb_png_of_requested_size() -> None:
    celsius = np.linspace(20, 30, H * W, dtype=np.float32).reshape(H, W)
    png = render_preview(celsius, size=(64, 48))
    img = Image.open(io.BytesIO(png))
    assert img.size == (64, 48) and img.mode == "RGB"


def test_render_keyframes_strip_geometry() -> None:
    frames = [np.full((H, W), 20.0 + k, dtype=np.float32) for k in range(12)]
    png = render_keyframes(frames, tile=(16, 12), vmin=20.0, vmax=31.0)
    img = Image.open(io.BytesIO(png))
    assert img.size == (16 * 12, 12)
    a = np.asarray(img.convert("L"), dtype=np.float32)
    assert a[:, :16].mean() < a[:, -16:].mean()  # brighter left -> right (shared scale)


def test_generate_previews_writes_files_and_manifest_without_touching_store(tmp_path: Path) -> None:
    d = _exp(tmp_path)
    before = _store_hash(d)
    out = generate_previews(d)
    assert (d / "preview.png").is_file() and (d / "keyframes.png").is_file()
    assert out["preview"]["frame_index"] == 10 and out["keyframes"]["count"] == 12
    assert out["keyframes"]["indices"][0] == 0 and out["keyframes"]["indices"][-1] == 19
    assert len(out["preview"]["sha256"]) == 64
    assert _store_hash(d) == before
    man = json.loads((d / "manifest.json").read_text())
    assert man["previews"]["preview"]["file"] == "preview.png"


def test_generate_previews_on_incomplete_experiment(tmp_path: Path) -> None:
    d = _exp(tmp_path, n=5, finalize=False)
    out = generate_previews(d)
    assert (d / "preview.png").is_file()
    assert out["preview"]["frame_index"] == 2
    assert not (d / "manifest.json").exists()  # never fabricate a manifest
