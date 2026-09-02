"""Preview/keyframe rendering: visualization-only PNGs derived from the store."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from flir_research_interface.analysis.preview import (
    IRON_LUT,
    generate_previews,
    render_keyframes,
    render_preview,
)
from flir_research_interface.camera.base import Frame
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.recording.recorder import Recorder

W, H = 32, 24


def _exp(
    root: Path, n: int = 20, finalize: bool = True, ir_format: str = "TemperatureLinear10mK"
) -> Path:
    rec = Recorder(None, experiments_root=root, chunk_frames=8)
    d = rec.start(
        name="pv",
        metadata={},
        camera_info={"backend": "simulated", "ir_format": ir_format},
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
                ir_format=ir_format,
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


def test_generate_previews_keyframe_indices_are_not_deduplicated(tmp_path: Path) -> None:
    d = _exp(tmp_path, n=5)
    out = generate_previews(d)
    assert out["keyframes"]["indices"] == [0, 0, 1, 1, 1, 2, 2, 3, 3, 3, 4, 4]
    assert len(out["keyframes"]["t_s"]) == 12


def test_generate_previews_radiometric_fallback_uses_counts_units(tmp_path: Path) -> None:
    d = _exp(tmp_path, n=10, ir_format="Radiometric")
    out = generate_previews(d)
    assert out["units"] == "counts"
    assert out["keyframes"]["vmax"] >= out["keyframes"]["vmin"]


def test_generate_previews_unknown_ir_format_does_not_raise(tmp_path: Path) -> None:
    d = _exp(tmp_path, n=10, ir_format="Weird")
    out = generate_previews(d)
    assert out["units"] == "counts"


def test_generate_previews_preserves_existing_manifest_fields(tmp_path: Path) -> None:
    d = _exp(tmp_path)
    generate_previews(d)
    manifest = json.loads((d / "manifest.json").read_text())
    assert manifest["complete"] is True
    assert "checksums" in manifest
    assert "gap_events" in manifest


def test_render_preview_hotspot_survives_downscale() -> None:
    frame = np.full((480, 640), 30.0, dtype=np.float32)
    frame[241, 321] = 90.0
    png = render_preview(frame)
    img = Image.open(io.BytesIO(png))
    rgb = np.asarray(img.convert("RGB"))
    assert (rgb == IRON_LUT[255]).all(axis=-1).any()


def test_render_preview_degenerate_span_is_mid_gray() -> None:
    celsius = np.full((H, W), 25.0, dtype=np.float32)
    png = render_preview(celsius)
    img = Image.open(io.BytesIO(png))
    rgb = np.asarray(img.convert("RGB"))
    assert (rgb == IRON_LUT[128]).all()


@pytest.mark.skip(
    reason=(
        "Cannot reach generate_previews's own n==0 guard through the public Recorder path: "
        "Recorder.stop() succeeds with frames_written=0, but the 'counts' array is only "
        "created lazily on the first submitted frame, so ExperimentReader(exp_dir) itself "
        "raises KeyError('counts') before generate_previews can run its ValueError check. "
        "This is a pre-existing gap in Recorder/ExperimentReader for zero-frame recordings, "
        "out of scope for this preview-rendering fix."
    )
)
def test_generate_previews_on_zero_frame_experiment_raises(tmp_path: Path) -> None:
    rec = Recorder(None, experiments_root=tmp_path, chunk_frames=8)
    d = rec.start(
        name="empty",
        metadata={},
        camera_info={"backend": "simulated", "ir_format": "TemperatureLinear10mK"},
    )
    rec.stop()
    with pytest.raises(ValueError, match="no frames"):
        generate_previews(d)


def test_generate_previews_writes_sidecar_readable_without_manifest(tmp_path: Path) -> None:
    """An incomplete experiment (no stop(), so no manifest.json) still exposes previews via
    a previews.json sidecar that ExperimentReader.info() picks up."""
    d = _exp(tmp_path, n=5, finalize=False)
    generate_previews(d)
    assert (d / "previews.json").is_file()
    assert not (d / "manifest.json").exists()
    info = ExperimentReader(d).info()
    assert info["previews"]["preview"]["file"] == "preview.png"
