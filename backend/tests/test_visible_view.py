"""Seeing the visible camera: recorded visible.mp4 in playback, live MJPEG preview (M9 view)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import numpy as np
from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.camera.base import Frame
from flir_research_interface.recording.recorder import Recorder
from flir_research_interface.visible.preview import MjpegRelay, mjpeg_command


def _experiment_with_video(root: Path) -> Path:
    rec = Recorder(None, experiments_root=root, chunk_frames=4)
    d = rec.start(name="vis", metadata={}, camera_info={"ir_format": "TemperatureLinear10mK"})
    rec.submit(
        Frame(
            frame_id=1, device_timestamp_ns=1, host_timestamp_ns=1, pixel_format="Mono16",
            ir_format="TemperatureLinear10mK", counts=np.zeros((4, 4), dtype=np.uint16),
            incomplete=False,
        )
    )
    rec.stop()
    (d / "visible.mp4").write_bytes(bytes(range(256)) * 4)  # 1024 fake bytes
    return d


def test_visible_mp4_is_served_with_range_support(tmp_path: Path) -> None:
    d = _experiment_with_video(tmp_path)
    app = create_app(default_backend="simulated", experiments_root=tmp_path)
    with TestClient(app) as c:
        full = c.get(f"/api/experiments/{d.name}/visible.mp4")
        assert full.status_code == 200 and full.headers["content-type"] == "video/mp4"
        assert len(full.content) == 1024 and full.headers.get("accept-ranges") == "bytes"
        part = c.get(f"/api/experiments/{d.name}/visible.mp4", headers={"Range": "bytes=256-511"})
        assert part.status_code == 206
        assert part.content == bytes(range(256))
        assert part.headers["content-range"] == "bytes 256-511/1024"
        assert c.get("/api/experiments/nope/visible.mp4").status_code == 404
        (d / "visible.mp4").unlink()
        assert c.get(f"/api/experiments/{d.name}/visible.mp4").status_code == 404


def test_mjpeg_command_transcodes_to_a_small_multipart_stream() -> None:
    cmd = mjpeg_command("/opt/ffmpeg", "rtsp://u:p@h/avc/ch1", fps=8, width=640)
    assert cmd[0] == "/opt/ffmpeg" and cmd[-1] == "-"
    assert cmd[cmd.index("-i") + 1] == "rtsp://u:p@h/avc/ch1"
    assert "-rtsp_transport" in cmd and "-timeout" in cmd
    assert cmd[cmd.index("-f") + 1] == "mpjpeg"
    assert "scale=640:-2" in " ".join(cmd) and cmd[cmd.index("-r") + 1] == "8"


class FakeStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self.stdout = io.BytesIO(b"".join(chunks))
        self.returncode: int | None = None
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.killed = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode or 0


def test_relay_yields_ffmpeg_output_and_stops_the_process_when_the_client_leaves() -> None:
    proc = FakeStream(
        [b"--ffmpeg\r\nContent-type: image/jpeg\r\n\r\nJPEG1", b"--ffmpeg\r\n...JPEG2"]
    )
    relay = MjpegRelay(cmd=["x"], popen=lambda *a, **k: proc)
    gen = relay.stream()
    body = b"".join(gen)
    assert body.startswith(b"--ffmpeg") and b"JPEG2" in body
    assert proc.killed is True  # ended: the process is torn down
    assert relay.content_type == "multipart/x-mixed-replace; boundary=ffmpeg"


def test_live_preview_endpoint_reports_unavailable_without_ffmpeg_or_credentials(
    tmp_path: Path,
) -> None:
    app = create_app(default_backend="simulated", experiments_root=tmp_path)
    with TestClient(app) as c:
        r = c.get("/api/visible/live.mjpeg")
        assert r.status_code == 503
        assert "unavailable" in r.json()["detail"]


def test_live_preview_endpoint_streams_from_the_factory(tmp_path: Path) -> None:
    def factory() -> Any:
        proc = FakeStream([b"--ffmpeg\r\nContent-type: image/jpeg\r\n\r\nJPEG1\r\n"])
        return MjpegRelay(cmd=["x"], popen=lambda *a, **k: proc)

    app = create_app(
        default_backend="simulated", experiments_root=tmp_path, preview_factory=factory
    )
    with TestClient(app) as c:
        with c.stream("GET", "/api/visible/live.mjpeg") as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("multipart/x-mixed-replace")
            body = b"".join(r.iter_bytes())
        assert b"JPEG1" in body
