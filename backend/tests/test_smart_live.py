"""Live smart ROI trackers on the camera stream (acquisition/smart_live) and the frame overlay.

Synthetic Frame objects only; never PySpin.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import numpy as np

from flir_research_interface.acquisition.smart_live import SmartLive
from flir_research_interface.analysis.smart_roi import HOLD_S
from flir_research_interface.api.frames import decode_frame_message, encode_frame_message
from flir_research_interface.camera.base import Frame

W, H = 640, 480
IRFMT = "TemperatureLinear100mK"  # 0.1 K/count: 600 °C fits in uint16
BOX = [[100, 100], [300, 100], [300, 260], [100, 260]]
SMART: dict[str, Any] = {"id": 7, "name": "sample", "kind": "smart", "search": BOX,
                         "rings_px": [5, 10, 25], "rule": "relative", "fixed_c": None,
                         "sensitivity": 0.5, "ring_emissivity": None}
CIRCLE = {"id": 10, "name": "c", "kind": "circle", "cx": 320, "cy": 240, "r": 20.0}


def _blob_c() -> np.ndarray:
    ys, xs = np.mgrid[0:H, 0:W]
    rho = np.sqrt(((xs - 200.0) / 30.0) ** 2 + ((ys - 180.0) / 20.0) ** 2)
    d = np.maximum(rho - 1.0, 0.0) * 20.0
    return np.where(rho <= 1.0, 600.0, 40.0 + 200.0 * np.exp(-d / 8.0))


def _frame(celsius: np.ndarray, t_s: float, fid: int = 1, fmt: str = IRFMT) -> Frame:
    counts = np.round((celsius + 273.15) / 0.1).astype(np.uint16)
    return Frame(frame_id=fid, device_timestamp_ns=int(t_s * 1e9),
                 host_timestamp_ns=int(t_s * 1e9), pixel_format="Mono16", ir_format=fmt,
                 counts=counts, incomplete=False)


def test_on_frame_locks_and_reports_latest() -> None:
    live = SmartLive()
    live.set_rois([SMART, CIRCLE])
    live.on_frame(_frame(_blob_c(), 10.0))
    (res,) = live.latest().values()
    assert live.latest().keys() == {7}
    assert res.state == "locked" and res.valid is True
    assert res.sample["mean_c"] is not None and abs(res.sample["mean_c"] - 600.0) < 0.1


def test_smart_live_keeps_tracker_on_unchanged_spec() -> None:
    live = SmartLive()
    live.set_rois([SMART])
    live.on_frame(_frame(_blob_c(), 10.0))
    first = live.tracker(7)
    assert first is not None
    live.set_rois([{**SMART, "name": "renamed"}])  # a rename is not a new spec
    live.on_frame(_frame(_blob_c(), 10.1, 2))
    assert live.tracker(7) is first
    assert live.latest()[7].state == "locked"
    live.set_rois([{**SMART, "sensitivity": 0.6}])  # changed spec: a fresh tracker, old result gone
    assert 7 not in live.latest()
    live.on_frame(_frame(_blob_c(), 10.2, 3))
    assert live.tracker(7) is not first


def test_removed_roi_drops_tracker_and_result() -> None:
    live = SmartLive()
    live.set_rois([SMART])
    live.on_frame(_frame(_blob_c(), 10.0))
    live.set_rois([CIRCLE])
    assert live.latest() == {} and live.tracker(7) is None and live.overlays() == []


def test_hold_then_search_on_live_timestamps() -> None:
    live = SmartLive()
    live.set_rois([SMART])
    live.on_frame(_frame(_blob_c(), 10.0))
    flat = np.full((H, W), 40.0)
    live.on_frame(_frame(flat, 10.1, 2))
    assert live.latest()[7].state == "holding" and live.latest()[7].valid is True
    live.on_frame(_frame(flat, 10.2 + HOLD_S, 3))
    assert live.latest()[7].state == "searching" and live.latest()[7].valid is False


def test_non_temperature_linear_frame_invalidates() -> None:
    live = SmartLive()
    live.set_rois([SMART])
    live.on_frame(_frame(_blob_c(), 10.0))
    live.on_frame(_frame(_blob_c(), 10.1, 2, fmt="Radiometric"))
    assert live.latest()[7].valid is False


def test_degenerate_smart_spec_never_raises() -> None:
    live = SmartLive()
    collinear = {**SMART, "id": 8, "search": [[0, 0], [1, 1], [2, 2]]}
    unparsable = {"id": 9, "kind": "smart", "search": [[0, 0]]}
    live.set_rois([collinear, unparsable, SMART])
    live.on_frame(_frame(_blob_c(), 10.0))
    got = live.latest()
    assert got[7].valid is True
    assert 8 not in got or got[8].valid is False
    assert 9 not in got


def test_tracker_exception_invalidates_only_that_roi(monkeypatch: Any) -> None:
    live = SmartLive()
    live.set_rois([SMART, {**SMART, "id": 8}])
    live.on_frame(_frame(_blob_c(), 10.0))
    bad = live.tracker(8)
    assert bad is not None

    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("tracker bug")

    monkeypatch.setattr(bad, "update", boom)
    live.on_frame(_frame(_blob_c(), 10.1, 2))
    assert live.latest()[7].valid is True and live.latest()[8].valid is False


def test_overlays_wire_shape() -> None:
    live = SmartLive()
    live.set_rois([SMART])
    assert live.overlays() == []
    live.on_frame(_frame(_blob_c(), 10.0))
    (ov,) = live.overlays()
    assert ov["id"] == 7 and ov["state"] == "locked" and ov["valid"] is True
    assert len(ov["bbox"]) == 4 and isinstance(ov["labels"], str) and ov["labels"]


def test_clear_forgets_tracks() -> None:
    live = SmartLive()
    live.set_rois([SMART])
    live.on_frame(_frame(_blob_c(), 10.0))
    live.clear()
    assert live.latest() == {} and live.tracker(7) is None
    live.on_frame(_frame(_blob_c(), 10.1, 2))  # specs are kept: tracks rebuild on the next frame
    assert live.latest()[7].state == "locked"


def test_concurrent_set_rois_and_frames() -> None:
    live = SmartLive()
    live.set_rois([SMART])
    stop = threading.Event()
    errors: list[BaseException] = []

    def reader() -> None:
        while not stop.is_set():
            try:
                live.set_rois([{**SMART, "sensitivity": 0.5 + 0.1 * (np.random.rand() > 0.5)}])
                live.latest()
                live.overlays()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

    th = threading.Thread(target=reader)
    th.start()
    for i in range(10):
        live.on_frame(_frame(_blob_c(), 10.0 + i / 30, i + 1))
    stop.set()
    th.join()
    assert errors == []


def test_ws_extra_carries_smart() -> None:
    overlay = [{"id": 7, "state": "locked", "valid": True, "bbox": [1, 2, 3, 4], "labels": "AQ=="}]
    msg = encode_frame_message(_frame(_blob_c(), 1.0), {"fps": 30.0}, extra={"smart": overlay})
    hdr, counts = decode_frame_message(msg)
    assert hdr["smart"] == overlay and counts.shape == (H, W)


def test_api_feed_and_ws_carry_smart(tmp_path: Path) -> None:
    import time

    from fastapi.testclient import TestClient

    from flir_research_interface.api.app import create_app

    app = create_app(default_backend="simulated", sim_fps=60.0, viz_fps=30.0,
                     experiments_root=tmp_path, min_free_gb=0.0)
    with TestClient(app) as c:
        assert c.put("/api/live/rois", json={"rois": [SMART, CIRCLE]}).json()["count"] == 2
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        time.sleep(0.3)
        p = c.get("/api/live/roi-temps").json()
        smart = next(r for r in p["rois"] if r["id"] == 7)
        assert smart["kind"] == "smart" and smart["state"] in ("searching", "locked", "holding")
        assert {"mean_c", "max_c", "min_c", "valid", "rings", "dims"} <= smart.keys()
        assert app.state.smart_live.tracker(7) is not None  # the listener is attached
        # the simulated camera has no hot sample: the controller must see invalid, not a number
        if smart["state"] == "searching":
            assert smart["valid"] is False and smart["mean_c"] is None
        with c.websocket_connect("/ws/frames") as ws:
            for _ in range(20):
                m = ws.receive()
                if m.get("bytes"):
                    hdr, _counts = decode_frame_message(m["bytes"])
                    break
            else:
                raise AssertionError("no frame message")
        assert [o["id"] for o in hdr["smart"]] == [7]
        c.post("/api/camera/disconnect")
        assert app.state.smart_live.latest() == {}
