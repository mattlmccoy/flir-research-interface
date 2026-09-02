"""Milestone 9: visible-camera recorder (ffmpeg stream copy of RTSP /avc/ch1, host-clock stamps).

The ffmpeg process is replaced by a fake so these tests need neither a camera nor ffmpeg; the
real command line is asserted verbatim (docs/visible_camera.md §2).
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.visible.recorder import (
    VisibleRecorder,
    VisibleState,
    ffmpeg_command,
)


class FakeProc:
    """Stands in for subprocess.Popen: records the argv, writes the output on 'q'."""

    instances: list[FakeProc] = []

    def __init__(self, args: list[str], **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs
        self.returncode: int | None = None
        self.stdin_data = b""
        self.out = Path(args[-1])
        FakeProc.instances.append(self)

        class _Stdin:
            def write(inner, data: bytes) -> None:  # noqa: N805
                self.stdin_data += data

            def flush(inner) -> None:  # noqa: N805
                pass

            def close(inner) -> None:  # noqa: N805
                pass

        self.stdin = _Stdin()

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            self.out.write_bytes(b"\x00\x00\x00\x1cftypisom" + b"x" * 100)
            self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9


def test_ffmpeg_command_is_a_tcp_stream_copy_with_wallclock_timestamps(tmp_path: Path) -> None:
    out = tmp_path / "visible.mp4"
    cmd = ffmpeg_command("/opt/ffmpeg", "rtsp://rtsp:pw@192.168.7.2/avc/ch1", out)
    assert cmd[0] == "/opt/ffmpeg"
    assert cmd[-1] == str(out)
    assert "-rtsp_transport" in cmd and cmd[cmd.index("-rtsp_transport") + 1] == "tcp"
    assert cmd[cmd.index("-i") + 1] == "rtsp://rtsp:pw@192.168.7.2/avc/ch1"
    assert "-c" in cmd and cmd[cmd.index("-c") + 1] == "copy"
    assert "-use_wallclock_as_timestamps" in cmd
    assert "-f" in cmd and cmd[cmd.index("-f") + 1] == "mp4"
    assert "-an" in cmd  # the ONVIF metadata track is dropped; video only


def test_recorder_start_stop_writes_mp4_and_sidecar(tmp_path: Path) -> None:
    FakeProc.instances.clear()
    rec = VisibleRecorder(
        ffmpeg="/opt/ffmpeg", url="rtsp://rtsp:secret@192.168.7.2/avc/ch1", popen=FakeProc
    )
    assert rec.state is VisibleState.IDLE
    t0 = time.time_ns()
    rec.start(tmp_path)
    assert rec.state is VisibleState.RECORDING
    st = rec.stats()
    assert st["state"] == "recording" and st["file"] == str(tmp_path / "visible.mp4")
    assert st["started_host_ns"] >= t0
    info = rec.stop()
    assert rec.state is VisibleState.IDLE
    proc = FakeProc.instances[-1]
    assert proc.stdin_data == b"q"  # graceful stop so the mp4 moov atom is written
    mp4 = tmp_path / "visible.mp4"
    assert mp4.is_file() and info["size_bytes"] == mp4.stat().st_size
    assert info["sha256"] == hashlib.sha256(mp4.read_bytes()).hexdigest()
    side = json.loads((tmp_path / "visible.json").read_text())
    assert side["returncode"] == 0 and side["stopped_host_ns"] >= side["started_host_ns"]
    assert "secret" not in json.dumps(side)  # credentials never land on disk
    assert side["url"].startswith("rtsp://rtsp:***@")
    assert side["sync"] == "host clock; ffmpeg -use_wallclock_as_timestamps 1"


def test_recorder_reports_ffmpeg_death_as_error(tmp_path: Path) -> None:
    class Dying(FakeProc):
        def poll(self) -> int | None:
            self.returncode = 1
            return 1

    rec = VisibleRecorder(ffmpeg="/opt/ffmpeg", url="rtsp://h/avc/ch1", popen=Dying)
    rec.start(tmp_path)
    assert rec.stats()["state"] == "error"
    assert "exited" in rec.stats()["error"]


def test_recorder_refuses_double_start(tmp_path: Path) -> None:
    rec = VisibleRecorder(ffmpeg="/opt/ffmpeg", url="rtsp://h/avc/ch1", popen=FakeProc)
    rec.start(tmp_path)
    with pytest.raises(RuntimeError):
        rec.start(tmp_path)
    rec.stop()


def _client(tmp_path: Path, **kw: Any) -> TestClient:
    app = create_app(
        default_backend="simulated",
        sim_fps=60.0,
        experiments_root=tmp_path,
        min_free_gb=0.0,
        **kw,
    )
    return TestClient(app)


def test_recording_with_visible_writes_mp4_next_to_the_store(tmp_path: Path) -> None:
    FakeProc.instances.clear()
    factory = lambda: VisibleRecorder(  # noqa: E731
        ffmpeg="/opt/ffmpeg", url="rtsp://rtsp:pw@192.168.7.2/avc/ch1", popen=FakeProc
    )
    with _client(tmp_path, visible_factory=factory) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        r = c.post("/api/recording/start", json={"name": "vis", "visible": True})
        assert r.status_code == 200, r.text
        assert r.json()["visible"]["state"] == "recording"
        st = c.get("/api/recording/status").json()
        assert st["visible"]["state"] == "recording"
        exp_dir = Path(st["experiment_dir"])
        time.sleep(0.2)
        man = c.post("/api/recording/stop").json()
        assert man["visible"]["returncode"] == 0
        assert (exp_dir / "visible.mp4").is_file() and (exp_dir / "visible.json").is_file()
        info = c.get(f"/api/experiments/{exp_dir.name}").json()
        assert info["visible"]["file"] == "visible.mp4"
        c.post("/api/camera/disconnect")


def test_recording_without_visible_support_reports_it(tmp_path: Path) -> None:
    with _client(tmp_path) as c:  # no factory: ffmpeg/credentials unavailable
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        r = c.post("/api/recording/start", json={"name": "novis", "visible": True})
        assert r.status_code == 200
        assert r.json()["visible"]["state"] == "unavailable"
        st = c.get("/api/recording/status").json()
        assert st["visible"]["state"] == "unavailable"
        c.post("/api/recording/stop")
        c.post("/api/camera/disconnect")


def test_default_factory_builds_the_ch1_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from flir_research_interface.visible import recorder as mod

    monkeypatch.setattr(mod, "find_ffprobe", lambda candidates: "/opt/ffmpeg")
    monkeypatch.setenv("FRI_CAMERA_HOST", "192.168.7.2")
    monkeypatch.setenv("FRI_RTSP_USER", "rtsp")
    monkeypatch.setenv("FRI_RTSP_PASSWORD", "p w")
    factory = mod.default_visible_factory(None)
    assert factory is not None
    rec = factory()
    assert rec.stats()["url"] == "rtsp://rtsp:***@192.168.7.2/avc/ch1"
    monkeypatch.delenv("FRI_RTSP_USER")
    assert mod.default_visible_factory(None) is None
