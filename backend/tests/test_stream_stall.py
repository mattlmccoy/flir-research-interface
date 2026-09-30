"""Stream-stall detection: no new frame for longer than the threshold while recording.

The replay tests drive the recorder with frame ids + host timestamps captured from two real
FLIR A70 runs (tests/fixtures/stream_stall_runs.json): 20260930_143846_Run, whose camera stopped
delivering 19.4 s before the operator pressed stop but whose manifest still said complete=True,
and 20260930_142445_Run, a healthy run whose last frame is 0.1 s before the stop.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from flir_research_interface.camera.base import Frame
from flir_research_interface.recording.recorder import Recorder, RecorderState

FIXTURE = Path(__file__).parent / "fixtures" / "stream_stall_runs.json"
CAMERA = {"model": "FLIR A70", "ir_format": "TemperatureLinear10mK"}
FRAME_NS = 33_333_333


class _Clock:
    """Host wall clock (ns) under test control."""

    def __init__(self, t_ns: int) -> None:
        self.t = t_ns

    def __call__(self) -> int:
        return self.t


def _ns(t_utc: str) -> int:
    dt = datetime.fromisoformat(t_utc)
    return int(dt.timestamp()) * 1_000_000_000 + dt.microsecond * 1000


def _frame(fid: int, host_ns: int) -> Frame:
    return Frame(
        frame_id=fid,
        device_timestamp_ns=host_ns,
        host_timestamp_ns=host_ns,
        pixel_format="Mono16",
        ir_format="TemperatureLinear10mK",
        counts=np.full((4, 4), 20000 + fid % 5000, dtype=np.uint16),
        incomplete=False,
    )


def _recorder(tmp_path: Path, clock: _Clock, **kw) -> Recorder:  # type: ignore[no-untyped-def]
    return Recorder(None, experiments_root=tmp_path, min_free_gb=0.0, clock=clock, **kw)


def _replay(tmp_path: Path, run: str) -> tuple[dict, list[dict], dict]:
    """Feed a captured run tail through a recorder, arriving at the real host times, then stop
    at the real ``recording_stopped`` time. The fixture holds only the tail of each run, so the
    recording starts one frame period before the first captured frame."""
    fx = json.loads(FIXTURE.read_text())[run]
    stopped = next(e for e in fx["events"] if e["type"] == "recording_stopped")
    clock = _Clock(fx["host_timestamp_ns"][0] - FRAME_NS)
    rec = _recorder(tmp_path, clock, chunk_frames=64, queue_frames=4096)  # instant replay
    d = rec.start(name="replay", metadata={}, camera_info=CAMERA)
    for fid, host_ns in zip(fx["frame_id"], fx["host_timestamp_ns"], strict=True):
        clock.t = host_ns
        rec.submit(_frame(fid, host_ns))
    clock.t = _ns(stopped["t_utc"])
    man = rec.stop()
    events = json.loads((d / "events.json").read_text())
    return man, events, stopped


def test_real_tail_stall_is_recorded_and_the_run_is_not_complete(tmp_path: Path) -> None:
    man, events, stopped = _replay(tmp_path, "20260930_143846_Run")
    assert man["stall_threshold_s"] == 2.0
    assert man["tail_gap_s"] == pytest.approx(19.447, abs=0.002)
    # the 0.85 s gaps and 12-frame id gaps around 18:42:15 stay below the threshold: one stall only
    assert len(man["stream_stalls"]) == 1
    stall = man["stream_stalls"][0]
    assert stall["tail"] is True
    assert stall["after_frame_id"] == 9389
    assert stall["duration_s"] == pytest.approx(19.447, abs=0.002)
    assert stall["end_utc"] == stopped["t_utc"]
    assert man["complete"] is False
    assert man["incomplete_reasons"] == ["stream_stalled"]
    kinds = [e["type"] for e in events]
    assert kinds[-2:] == ["stream_stall", "recording_stopped"]
    assert events[-1]["t_utc"] == stopped["t_utc"]


def test_real_healthy_run_tail_is_not_a_stall(tmp_path: Path) -> None:
    man, events, _ = _replay(tmp_path, "20260930_142445_Run")
    assert man["tail_gap_s"] == pytest.approx(0.0996, abs=0.001)
    assert man["stream_stalls"] == []
    assert man["complete"] is True
    assert man["incomplete_reasons"] == []
    assert "stream_stall" not in [e["type"] for e in events]


def test_mid_run_stall_is_recorded_and_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    clock = _Clock(1_000 * FRAME_NS)
    rec = _recorder(tmp_path, clock)
    d = rec.start(name="gap", metadata={}, camera_info=CAMERA)
    t = clock.t
    with caplog.at_level(logging.WARNING, logger="flir_research_interface.recording.recorder"):
        for fid in range(20):
            t += 3_000_000_000 if fid == 10 else FRAME_NS
            clock.t = t
            rec.submit(_frame(fid, t))
    clock.t = t + FRAME_NS
    man = rec.stop()
    assert len(man["stream_stalls"]) == 1
    stall = man["stream_stalls"][0]
    assert stall["tail"] is False
    assert (stall["after_frame_id"], stall["resumed_frame_id"]) == (9, 10)
    assert stall["duration_s"] == pytest.approx(3.0)
    assert man["complete"] is False and man["incomplete_reasons"] == ["stream_stalled"]
    assert "stream_stall" in [e["type"] for e in json.loads((d / "events.json").read_text())]
    assert any("stream stall" in r.getMessage() for r in caplog.records)


def test_periodic_recording_is_judged_on_every_received_frame(tmp_path: Path) -> None:
    """every_nth=100 at 30 fps stores a frame every 3.3 s; the camera never stalled."""
    clock = _Clock(1_000 * FRAME_NS)
    rec = _recorder(tmp_path, clock, every_nth=100)
    rec.start(name="lapse", metadata={}, camera_info=CAMERA)
    for fid in range(300):
        clock.t += FRAME_NS
        rec.submit(_frame(fid, clock.t))
    clock.t += FRAME_NS
    man = rec.stop()
    assert man["stream_stalls"] == [] and man["complete"] is True


def test_recording_that_never_receives_a_frame_is_a_stall(tmp_path: Path) -> None:
    clock = _Clock(1_000 * FRAME_NS)
    rec = _recorder(tmp_path, clock)
    rec.start(name="dark", metadata={}, camera_info=CAMERA)
    clock.t += 3_000_000_000
    man = rec.stop()
    assert man["tail_gap_s"] == pytest.approx(3.0)
    assert [s["after_frame_id"] for s in man["stream_stalls"]] == [None]
    assert man["complete"] is False


def test_live_stats_flag_frames_that_stopped_arriving(tmp_path: Path) -> None:
    clock = _Clock(1_000 * FRAME_NS)
    rec = _recorder(tmp_path, clock)
    rec.start(name="live", metadata={}, camera_info=CAMERA)
    clock.t += FRAME_NS
    rec.submit(_frame(1, clock.t))
    st = rec.stats()
    assert st["last_frame_age_s"] == pytest.approx(0.0) and st["stream_stalled"] is False
    clock.t += 5_000_000_000
    st = rec.stats()
    assert st["last_frame_age_s"] == pytest.approx(5.0)
    assert st["stream_stalled"] is True
    assert st["stall_threshold_s"] == 2.0
    rec.stop()


def test_stall_threshold_is_configurable(tmp_path: Path) -> None:
    clock = _Clock(1_000 * FRAME_NS)
    rec = _recorder(tmp_path, clock, stall_threshold_s=10.0)
    rec.start(name="slow", metadata={}, camera_info=CAMERA)
    clock.t += 5_000_000_000
    man = rec.stop()
    assert man["stall_threshold_s"] == 10.0 and man["stream_stalls"] == []


def test_recorder_error_is_not_misreported_as_a_camera_stall(tmp_path: Path) -> None:
    """Once the writer fails the recorder stops accepting frames itself; the silence that follows
    is the writer error, not the camera stream."""
    free = {"gb": 5.0}
    clock = _Clock(1_000 * FRAME_NS)
    rec = Recorder(
        None,
        experiments_root=tmp_path,
        min_free_gb=1.0,
        free_space_gb=lambda _p: free["gb"],
        clock=clock,
    )
    rec.start(name="disk", metadata={}, camera_info=CAMERA)
    clock.t += FRAME_NS
    rec.submit(_frame(1, clock.t))
    free["gb"] = 0.2
    clock.t += FRAME_NS
    rec.submit(_frame(2, clock.t))
    deadline = time.monotonic() + 3.0
    while rec.state != RecorderState.ERROR and time.monotonic() < deadline:
        time.sleep(0.01)
    assert rec.state == RecorderState.ERROR
    clock.t += 10_000_000_000  # the operator notices and stops 10 s later
    man = rec.stop()
    assert man["incomplete_reasons"] == ["writer_error"]
    assert man["stream_stalls"] == []
