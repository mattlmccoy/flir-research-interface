"""Tests for the validation-mode CLI helpers (fri-live)."""

from __future__ import annotations

import numpy as np

from flir_research_interface.analysis.stats import RectangleRoi, Spot
from flir_research_interface.camera.base import Frame
from flir_research_interface.validation import (
    csv_header,
    frame_row,
    parse_roi,
    parse_spot,
    summarize_rows,
)


def _frame(fid: int, ts_ns: int, center_counts: int) -> Frame:
    counts = np.full((4, 6), 29815, dtype=np.uint16)  # 25.00 C at 10 mK
    counts[2, 3] = center_counts
    return Frame(
        frame_id=fid,
        device_timestamp_ns=ts_ns,
        host_timestamp_ns=ts_ns + 5,
        pixel_format="Mono16",
        ir_format="TemperatureLinear10mK",
        counts=counts,
        incomplete=False,
    )


def test_parse_spot_and_roi() -> None:
    assert parse_spot("320,240") == Spot(x=320, y=240)
    assert parse_roi("10,20,110,220") == RectangleRoi(x0=10, y0=20, x1=110, y1=220)


def test_csv_header_lists_frame_spots_and_rois_in_order() -> None:
    hdr = csv_header(spots=[Spot(1, 2)], rois=[RectangleRoi(0, 0, 2, 2)])
    assert hdr[:4] == ["time_s", "frame_id", "device_timestamp_ns", "host_timestamp_ns"]
    assert (
        "center_C" in hdr
        and "frame_min_C" in hdr
        and "frame_max_C" in hdr
        and "frame_mean_C" in hdr
    )
    assert "spot1_x1_y2_C" in hdr
    assert {"roi1_mean_C", "roi1_min_C", "roi1_max_C", "roi1_std_C"} <= set(hdr)


def test_frame_row_converts_counts_and_uses_relative_time() -> None:
    f = _frame(fid=7, ts_ns=2_000_000_000, center_counts=47315)  # 200.00 C at center (x=3,y=2)
    row = frame_row(f, t0_ns=1_000_000_000, spots=[Spot(0, 0)], rois=[RectangleRoi(0, 0, 2, 2)])
    assert row["time_s"] == 1.0 and row["frame_id"] == 7
    assert abs(row["center_C"] - 200.0) < 0.011
    assert abs(row["spot1_x0_y0_C"] - 25.0) < 0.011
    assert abs(row["frame_max_C"] - 200.0) < 0.011 and abs(row["frame_min_C"] - 25.0) < 0.011
    assert abs(row["roi1_mean_C"] - 25.0) < 0.011


def test_summarize_rows_reports_frame_rate_and_center_stats() -> None:
    rows = [
        frame_row(_frame(i, i * 33_000_000, 29815 + i), t0_ns=0, spots=[], rois=[])
        for i in range(10)
    ]
    s = summarize_rows(rows)
    assert s["frames"] == 10
    assert abs(s["duration_s"] - 0.297) < 1e-6
    assert 29 < s["fps_from_device_timestamps"] < 31
    assert s["center_C_mean"] > 25.0
    assert s["frame_id_gaps"] == 0
