"""The RF-banding filter on the wire: a display copy rides alongside the raw counts on request.

Raw counts stay first and unchanged (ROI readouts and stats keep using them); the filtered copy
only follows when ``rf_notch`` is asked for, and its header says what was removed.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from flir_research_interface.analysis.rf_notch import rf_notch
from flir_research_interface.api.app import create_app
from flir_research_interface.api.frames import (
    decode_display_counts,
    decode_frame_message,
    encode_frame_message,
)
from flir_research_interface.camera.base import Frame
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.recording.recorder import Recorder

FX = np.load(Path(__file__).parent / "fixtures" / "rf_banding_frames.npz")


def _frame(counts: np.ndarray, fid: int = 1) -> Frame:
    return Frame(
        frame_id=fid,
        device_timestamp_ns=fid * 33_333_333,
        host_timestamp_ns=fid,
        pixel_format="Mono16",
        ir_format="TemperatureLinear10mK",
        counts=counts,
        incomplete=False,
    )


def _client(root: Path | None = None) -> TestClient:
    return TestClient(
        create_app(
            default_backend="simulated", sim_fps=60.0, experiments_root=root, min_free_gb=0.0
        )
    )


def test_without_the_flag_the_message_is_unchanged() -> None:
    msg = encode_frame_message(_frame(FX["pre_riser_rf_on"]))
    header, data = decode_frame_message(msg)
    assert "display" not in header
    assert decode_display_counts(msg) is None
    np.testing.assert_array_equal(data, FX["pre_riser_rf_on"])


def test_with_the_flag_the_raw_counts_stay_first_and_the_filtered_copy_follows() -> None:
    raw = FX["pre_riser_rf_on"]
    msg = encode_frame_message(_frame(raw), rf_notch=True)
    header, data = decode_frame_message(msg)
    np.testing.assert_array_equal(data, raw)  # numbers keep using the raw counts
    want, info = rf_notch(raw, 0.01)
    assert header["display"] == {"rf_notch": info, "counts": True}
    np.testing.assert_array_equal(decode_display_counts(msg), want)


def test_live_websocket_sends_the_display_copy_when_asked() -> None:
    with _client() as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        with c.websocket_connect("/ws/frames?rf_notch=1") as ws:
            msg = ws.receive_bytes()
            header, data = decode_frame_message(msg)
            assert header["display"]["rf_notch"]["applied"] is True
            assert decode_display_counts(msg).shape == data.shape
        with c.websocket_connect("/ws/frames") as ws:
            assert "display" not in decode_frame_message(ws.receive_bytes())[0]
        c.post("/api/camera/disconnect")


def test_playback_frames_carry_the_display_copy_when_asked(tmp_path: Path) -> None:
    rec = Recorder(None, experiments_root=tmp_path, chunk_frames=4, min_free_gb=0.0)
    d = rec.start(name="banded", metadata={}, camera_info={"ir_format": "TemperatureLinear10mK"})
    for i, key in enumerate(("pre_riser_rf_off", "pre_riser_rf_on")):
        rec.submit(_frame(FX[key], i + 1))
    rec.stop()
    n = ExperimentReader(d).n_frames
    assert n == 2
    with _client(tmp_path) as c:
        block = c.get(f"/api/experiments/{d.name}/frames?start=0&count=2&rf_notch=1").content
        msgs, off = [], 0
        while off < len(block):
            ln = int.from_bytes(block[off : off + 4], "big")
            msgs.append(block[off + 4 : off + 4 + ln])
            off += 4 + ln
        bands = [decode_frame_message(m)[0]["display"]["rf_notch"]["bands"] for m in msgs]
        assert bands == [[], ["diag+", "diag-"]]
        single = c.get(f"/api/experiments/{d.name}/frames/1?rf_notch=1").content
        assert decode_frame_message(single)[0]["display"]["rf_notch"]["bands"] == ["diag+", "diag-"]
        plain = c.get(f"/api/experiments/{d.name}/frames/1").content
        assert "display" not in decode_frame_message(plain)[0]
