"""Tests for the scientific recorder (Zarr v2 store, bounded queue, accounting, recovery)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pytest
import zarr

from flir_research_interface.acquisition.service import AcquisitionService
from flir_research_interface.camera.base import Frame
from flir_research_interface.camera.simulated import SimulatedCameraBackend, UniformScene
from flir_research_interface.recording.recorder import (
    Recorder,
    RecorderState,
    inspect_experiment,
)

W, H = 32, 24


def _frame(fid: int, ts: int = 0) -> Frame:
    return Frame(
        frame_id=fid,
        device_timestamp_ns=ts or fid * 33_000_000,
        host_timestamp_ns=fid * 33_000_000 + 7,
        pixel_format="Mono16",
        ir_format="TemperatureLinear10mK",
        counts=np.full((H, W), 29815 + fid, dtype=np.uint16),
        incomplete=False,
    )


def _wait(pred, timeout_s: float = 3.0) -> bool:  # type: ignore[no-untyped-def]
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.005)
    return False


def test_record_from_simulated_service_writes_every_frame(tmp_path: Path) -> None:
    cam = SimulatedCameraBackend(
        scene=UniformScene(25.0), width=W, height=H, fps=200.0, realtime=True
    )
    svc = AcquisitionService(cam)
    svc.connect(svc.enumerate()[0])
    rec = Recorder(svc, experiments_root=tmp_path, chunk_frames=16)
    svc.start()
    try:
        exp_dir = rec.start(name="Run_001", metadata={"operator": "test", "material": "PA12"})
        assert rec.state == RecorderState.RECORDING
        assert _wait(lambda: rec.stats()["frames_written"] >= 40, timeout_s=5.0)
        summary = rec.stop()
    finally:
        svc.disconnect()
    assert rec.state == RecorderState.IDLE
    st = rec.stats()
    assert summary["frames_written"] == st["frames_received"] > 0
    assert st["queue_dropped"] == 0
    assert st["min_free_gb"] == 2.0  # default guard threshold surfaces to the frontend too
    g = zarr.open_group(str(exp_dir / "thermal.zarr"), mode="r")
    counts = g["counts"]
    assert counts.shape == (summary["frames_written"], H, W) and counts.dtype == np.uint16
    fids = np.asarray(g["frame_id"][:])
    assert np.all(np.diff(fids) == 1)
    dts = np.diff(np.asarray(g["device_timestamp_ns"][:]))
    assert np.all(dts > 0)
    meta = json.loads((exp_dir / "metadata.json").read_text())
    assert meta["experiment"]["operator"] == "test" and meta["camera"]["backend"] == "simulated"
    assert meta["software"]["version"] and "conversion" in meta
    man = json.loads((exp_dir / "manifest.json").read_text())
    assert man["frames_written"] == summary["frames_written"] and man["complete"] is True
    assert man["frame_id_gaps"] == 0


def test_frame_id_gaps_are_detected_and_recorded(tmp_path: Path) -> None:
    rec = Recorder(None, experiments_root=tmp_path, chunk_frames=4)
    rec.start(
        name="gaps",
        metadata={},
        camera_info={"backend": "simulated", "ir_format": "TemperatureLinear10mK"},
    )
    for fid in (1, 2, 3, 6, 7, 10):  # missing 4,5 and 8,9
        rec.submit(_frame(fid))
    summary = rec.stop()
    assert summary["frames_written"] == 6
    assert summary["frame_id_gaps"] == 4
    assert summary["gap_events"] == [
        {"after_frame_id": 3, "missing": 2},
        {"after_frame_id": 7, "missing": 2},
    ]


def test_queue_overflow_is_counted_never_silent(tmp_path: Path) -> None:
    rec = Recorder(None, experiments_root=tmp_path, chunk_frames=4, queue_frames=2)
    rec.start(name="overflow", metadata={}, camera_info={"backend": "simulated"})
    rec.pause_writer_for_test()
    for fid in range(10):
        rec.submit(_frame(fid))
    rec.resume_writer_for_test()
    summary = rec.stop()
    assert summary["queue_dropped"] > 0
    assert summary["frames_written"] + summary["queue_dropped"] == 10
    assert summary["complete"] is False  # a recording with lost frames is flagged


def test_disk_guard_refuses_to_start_and_stops_when_low(tmp_path: Path) -> None:
    free = {"gb": 0.5}
    rec = Recorder(
        None, experiments_root=tmp_path, min_free_gb=1.0, free_space_gb=lambda _p: free["gb"]
    )
    with pytest.raises(RuntimeError, match="free space"):
        rec.start(name="low", metadata={}, camera_info={})
    free["gb"] = 5.0
    rec.start(name="low", metadata={}, camera_info={})
    rec.submit(_frame(1))
    free["gb"] = 0.2
    rec.submit(_frame(2))
    assert _wait(lambda: rec.state == RecorderState.ERROR)
    summary = rec.stop()
    assert "free space" in (summary["error"] or "")


def test_inspect_incomplete_experiment_without_manifest(tmp_path: Path) -> None:
    rec = Recorder(None, experiments_root=tmp_path, chunk_frames=4)
    exp_dir = rec.start(name="crash", metadata={}, camera_info={"backend": "simulated"})
    for fid in range(6):
        rec.submit(_frame(fid))
    rec.flush_for_test()
    info = inspect_experiment(exp_dir)  # simulate a crash: no stop(), no manifest yet
    assert info["complete"] is False and info["manifest"] is None
    assert info["frames_on_disk"] == 6
    assert info["has_metadata"] is True
    rec.stop()
    info2 = inspect_experiment(exp_dir)
    assert info2["complete"] is True and info2["frames_on_disk"] == 6


def test_experiment_directory_name_is_dated_and_unique(tmp_path: Path) -> None:
    rec = Recorder(None, experiments_root=tmp_path)
    d1 = rec.start(name="PA12 Run 1", metadata={}, camera_info={})
    rec.stop()
    d2 = rec.start(name="PA12 Run 1", metadata={}, camera_info={})
    rec.stop()
    assert d1 != d2 and d1.parent == tmp_path
    assert d1.name.split("_", 2)[2].startswith("PA12_Run_1")  # YYYYMMDD_HHMMSS_<slug>
