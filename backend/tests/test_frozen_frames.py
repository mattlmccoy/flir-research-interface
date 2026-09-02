"""The A70 repeats its last frame (new frame id + timestamp, identical pixels) during a NUC.
Such frames are kept (the record is what the camera sent) but counted and flagged."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from flir_research_interface.camera.base import Frame
from flir_research_interface.recording.recorder import Recorder


def _frame(i: int, fill: int) -> Frame:
    return Frame(
        frame_id=i,
        device_timestamp_ns=i * 33_333_333,
        host_timestamp_ns=i,
        pixel_format="Mono16",
        ir_format="TemperatureLinear10mK",
        counts=np.full((8, 8), fill, dtype=np.uint16),
        incomplete=False,
    )


def test_repeated_frames_are_counted_and_logged_as_a_frozen_run(tmp_path: Path) -> None:
    rec = Recorder(None, experiments_root=tmp_path, chunk_frames=4, min_free_gb=0.0)
    d = rec.start(name="fz", metadata={}, camera_info={"ir_format": "TemperatureLinear10mK"})
    fills = [1, 2, 3, 3, 3, 3, 4, 5, 5, 6]  # one frozen run of 3 repeats, one of 1 repeat
    for i, f in enumerate(fills):
        rec.submit(_frame(i, f))
    rec.flush_for_test()
    assert rec.stats()["repeated_frames"] == 4
    man = rec.stop()
    assert man["repeated_frames"] == 4 and man["frozen_runs"] == 2
    assert man["complete"] is True  # camera-side, like frame_id gaps: flagged, not fatal
    ev = [e for e in json.loads((d / "events.json").read_text()) if e["type"] == "frozen_frames"]
    assert [(e["first_frame_id"], e["last_frame_id"], e["repeats"]) for e in ev] == [
        (3, 5, 3),
        (8, 8, 1),
    ]
