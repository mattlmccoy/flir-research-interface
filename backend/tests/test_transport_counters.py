"""Transport counters attribute frame-id gaps: the manifest records how many frames the network
lost and how many the driver's buffer queue dropped *during this recording* (deltas, not totals
since the stream opened)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from flir_research_interface.camera.base import Frame
from flir_research_interface.recording.recorder import Recorder


def _frame(i: int) -> Frame:
    return Frame(
        frame_id=i,
        device_timestamp_ns=i * 33_333_333,
        host_timestamp_ns=i,
        pixel_format="Mono16",
        ir_format="TemperatureLinear10mK",
        counts=np.full((4, 4), 30000 + i, np.uint16),
        incomplete=False,
    )


class _Counters:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {"lost": 5, "dropped": 2, "missed_packets": 100, "x": None}

    def __call__(self) -> dict[str, Any]:
        return dict(self.values)


def test_manifest_records_transport_losses_during_the_recording(tmp_path: Path) -> None:
    c = _Counters()
    rec = Recorder(None, experiments_root=tmp_path, min_free_gb=0.0, transport_stats=c)
    rec.start(name="t", metadata={}, camera_info={"ir_format": "TemperatureLinear10mK"})
    rec.submit(_frame(0))
    c.values.update(lost=7, dropped=2, missed_packets=160)
    assert rec.stats()["transport"] == {"lost": 2, "dropped": 0, "missed_packets": 60}
    man = rec.stop()
    assert man["transport"] == {"lost": 2, "dropped": 0, "missed_packets": 60}


def test_no_transport_counters_is_none_and_a_failing_read_never_breaks_recording(
    tmp_path: Path,
) -> None:
    rec = Recorder(None, experiments_root=tmp_path, min_free_gb=0.0)
    rec.start(name="t", metadata={}, camera_info={"ir_format": "TemperatureLinear10mK"})
    assert rec.stop()["transport"] is None

    def boom() -> dict[str, Any]:
        raise RuntimeError("node read failed")

    rec = Recorder(None, experiments_root=tmp_path, min_free_gb=0.0, transport_stats=boom)
    rec.start(name="t2", metadata={}, camera_info={"ir_format": "TemperatureLinear10mK"})
    rec.submit(_frame(0))
    man = rec.stop()
    assert man["transport"] is None and man["frames_written"] == 1
