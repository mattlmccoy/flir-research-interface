"""Block frame fetch: one HTTP request returns many frames, so playback isn't one round-trip
per frame. The body is repeated [uint32 length][frame message]; the last frame matches the
single-frame endpoint byte-for-byte."""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.api.frames import decode_frame_message
from flir_research_interface.camera.base import Frame
from flir_research_interface.recording.recorder import Recorder


def _exp(root: Path, n: int = 20) -> str:
    rec = Recorder(None, experiments_root=root, chunk_frames=8)
    d = rec.start(
        name="blk",
        metadata={},
        camera_info={"backend": "sim", "ir_format": "TemperatureLinear10mK"},
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
    return d.name


def _split(body: bytes) -> list[bytes]:
    out, off = [], 0
    while off < len(body):
        (ln,) = struct.unpack_from(">I", body, off)
        off += 4
        out.append(body[off : off + ln])
        off += ln
    return out


def test_block_returns_a_run_of_frames(tmp_path: Path) -> None:
    name = _exp(tmp_path)
    with TestClient(create_app(experiments_root=tmp_path)) as c:
        r = c.get(f"/api/experiments/{name}/frames?start=3&count=5")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/octet-stream"
        assert r.headers["x-frame-start"] == "3" and r.headers["x-frame-count"] == "5"
        msgs = _split(r.content)
        assert len(msgs) == 5
        for k, msg in enumerate(msgs):
            hdr, data = decode_frame_message(msg)
            assert hdr["index"] == 3 + k and int(data[0, 0]) == 30003 + k
        # matches the single-frame endpoint exactly
        one = c.get(f"/api/experiments/{name}/frames/5").content
        assert msgs[2] == one


def test_block_clamps_and_validates(tmp_path: Path) -> None:
    name = _exp(tmp_path)
    with TestClient(create_app(experiments_root=tmp_path)) as c:
        r = c.get(f"/api/experiments/{name}/frames?start=18&count=100")
        assert len(_split(r.content)) == 2 and r.headers["x-frame-count"] == "2"  # clamped to n
        assert c.get(f"/api/experiments/{name}/frames?start=99&count=4").status_code == 404
        assert c.get(f"/api/experiments/{name}/frames?start=0&count=0").status_code == 422
        assert c.get(f"/api/experiments/{name}/frames?start=0&count=999").status_code == 422
