"""Preview endpoints and finalize-time preview generation."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.camera.base import Frame
from flir_research_interface.recording.recorder import Recorder


def _exp(root: Path, n: int = 6) -> Path:
    rec = Recorder(None, experiments_root=root, chunk_frames=4)
    d = rec.start(
        name="pv",
        metadata={},
        camera_info={"backend": "simulated", "ir_format": "TemperatureLinear10mK"},
    )
    for i in range(n):
        rec.submit(
            Frame(
                frame_id=i,
                device_timestamp_ns=i * 33_000_000,
                host_timestamp_ns=i,
                pixel_format="Mono16",
                ir_format="TemperatureLinear10mK",
                counts=np.full((8, 10), 30000 + i, np.uint16),
                incomplete=False,
            )
        )
    rec.stop()
    return d


def test_finalize_writes_previews_and_manifest_lists_them(tmp_path: Path) -> None:
    d = _exp(tmp_path)
    assert (d / "preview.png").is_file() and (d / "keyframes.png").is_file()
    man = json.loads((d / "manifest.json").read_text())
    assert man["previews"]["preview"]["file"] == "preview.png"
    assert man["previews"]["units"] == "celsius"
    assert man["complete"] is True


def test_preview_endpoints_serve_png_and_listing_exposes_previews(tmp_path: Path) -> None:
    d = _exp(tmp_path)
    with TestClient(create_app(experiments_root=tmp_path)) as c:
        r = c.get(f"/api/experiments/{d.name}/preview.png")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        assert r.content[:4] == b"\x89PNG"
        r = c.get(f"/api/experiments/{d.name}/keyframes.png")
        assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
        items = c.get("/api/experiments").json()
        assert items[0]["previews"]["keyframes"]["count"] == 12
        info = c.get(f"/api/experiments/{d.name}").json()
        assert info["previews"]["preview"]["frame_index"] == 3
        (d / "preview.png").unlink()
        assert c.get(f"/api/experiments/{d.name}/preview.png").status_code == 404
        r = c.post(f"/api/experiments/{d.name}/previews")
        assert r.status_code == 200 and (d / "preview.png").is_file()
        assert r.json()["units"] == "celsius"
        assert c.get("/api/experiments/nope/preview.png").status_code == 404


def test_finalize_survives_preview_failure(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import flir_research_interface.analysis.preview as pv

    def boom(_d: Path) -> dict:  # type: ignore[type-arg]
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr(pv, "generate_previews", boom)
    d = _exp(tmp_path)
    man = json.loads((d / "manifest.json").read_text())
    assert man["complete"] is True
    assert man["previews"] is None
    assert not (d / "preview.png").exists()
