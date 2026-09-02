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
    MAX_RESTARTS,
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
    # an unreachable camera must fail fast instead of "recording" nothing
    assert "-timeout" in cmd and cmd.index("-timeout") < cmd.index("-i")


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

    rec = VisibleRecorder(
        ffmpeg="/opt/ffmpeg", url="rtsp://h/avc/ch1", popen=Dying, restart_delay_s=0.0
    )
    rec.start(tmp_path)
    for _ in range(10):  # each poll may relaunch once; it gives up after MAX_RESTARTS
        if rec.stats()["state"] == "error":
            break
    st = rec.stats()
    assert st["state"] == "error" and st["restarts"] == MAX_RESTARTS
    assert "exited" in st["error"] and f"after {MAX_RESTARTS} retries" in st["error"]


def test_recorder_relaunches_ffmpeg_when_the_rtsp_open_fails_at_start(tmp_path: Path) -> None:
    """Seen on the A70 (2026-09-02 16:02): the camera refuses a new RTSP session for a moment
    after the previous one closed; ffmpeg exits 183 within a second with nothing written."""
    launches: list[FakeProc] = []

    class FlakyOpen(FakeProc):
        def __init__(self, args: list[str], **kwargs: Any) -> None:
            super().__init__(args, **kwargs)
            launches.append(self)
            if len(launches) <= 2:
                self.returncode = 183  # "Error opening input" before any packet

    rec = VisibleRecorder(
        ffmpeg="/opt/ffmpeg", url="rtsp://h/avc/ch1", popen=FlakyOpen, restart_delay_s=0.0
    )
    rec.start(tmp_path)
    for _ in range(5):
        rec.stats()
    st = rec.stats()
    assert st["state"] == "recording" and st["restarts"] == 2 and st["error"] is None
    assert len(launches) == 3 and launches[2].args == launches[0].args
    info = rec.stop()
    assert info["restarts"] == 2 and info["returncode"] == 0


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


def test_zero_byte_output_is_an_error_not_a_recording(tmp_path: Path) -> None:
    class Empty(FakeProc):
        def wait(self, timeout: float | None = None) -> int:
            if self.returncode is None:
                self.out.write_bytes(b"")
                self.returncode = 0
            return self.returncode

    rec = VisibleRecorder(ffmpeg="/opt/ffmpeg", url="rtsp://rtsp:pw@h/avc/ch1", popen=Empty)
    rec.start(tmp_path)
    info = rec.stop()
    assert info["error"] and "no video data" in info["error"]
    assert info["file"] is None and info["size_bytes"] == 0
    assert not (tmp_path / "visible.mp4").exists()  # an empty MP4 is worse than none
    side = json.loads((tmp_path / "visible.json").read_text())
    assert side["error"] == info["error"]


def test_stderr_tail_is_kept_for_diagnosis(tmp_path: Path) -> None:
    import io

    class Chatty(FakeProc):
        def __init__(self, args: list[str], **kwargs: Any) -> None:
            super().__init__(args, **kwargs)
            self.stderr = io.BytesIO(b"[rtsp @ 0x1] Connection to tcp://h:554 failed: timeout\n")

    rec = VisibleRecorder(ffmpeg="/opt/ffmpeg", url="rtsp://rtsp:pw@h/avc/ch1", popen=Chatty)
    rec.start(tmp_path)
    time.sleep(0.05)
    info = rec.stop()
    assert any("Connection to tcp://h:554 failed" in ln for ln in info["stderr_tail"])


def test_stderr_tail_never_contains_the_password(tmp_path: Path) -> None:
    import io

    class Leaky(FakeProc):
        def __init__(self, args: list[str], **kwargs: Any) -> None:
            super().__init__(args, **kwargs)
            self.stderr = io.BytesIO(
                b"Error opening input file rtsp://rtsp:s3cret@192.168.7.2/avc/ch1.\n"
                b"password was s3cret again\n"
            )

    rec = VisibleRecorder(
        ffmpeg="/opt/ffmpeg", url="rtsp://rtsp:s3cret@192.168.7.2/avc/ch1", popen=Leaky
    )
    rec.start(tmp_path)
    time.sleep(0.05)
    assert "s3cret" not in json.dumps(rec.stats())
    info = rec.stop()
    assert "s3cret" not in json.dumps(info)
    assert "s3cret" not in (tmp_path / "visible.json").read_text()
    assert any("rtsp://rtsp:***@192.168.7.2/avc/ch1" in ln for ln in info["stderr_tail"])


def test_stop_records_measured_stream_facts_from_the_probe(tmp_path: Path) -> None:
    probed: list[Path] = []

    def probe(path: Path) -> dict[str, Any]:
        probed.append(path)
        return {"frames": 79, "duration_s": 6.4673, "width": 1280, "height": 960, "codec": "h264"}

    rec = VisibleRecorder(ffmpeg="/opt/ffmpeg", url="rtsp://h/avc/ch1", popen=FakeProc, probe=probe)
    rec.start(tmp_path)
    info = rec.stop()
    assert probed == [tmp_path / "visible.mp4"]
    assert info["frames"] == 79 and info["duration_s"] == 6.4673
    assert abs(info["measured_fps"] - 79 / 6.4673) < 1e-6
    side = json.loads((tmp_path / "visible.json").read_text())
    assert side["measured_fps"] == info["measured_fps"] and side["codec"] == "h264"


def test_probe_failure_does_not_break_stop(tmp_path: Path) -> None:
    def bad(path: Path) -> dict[str, Any]:
        raise RuntimeError("ffprobe missing")

    rec = VisibleRecorder(ffmpeg="/opt/ffmpeg", url="rtsp://h/avc/ch1", popen=FakeProc, probe=bad)
    rec.start(tmp_path)
    info = rec.stop()
    assert info["returncode"] == 0 and info["measured_fps"] is None
