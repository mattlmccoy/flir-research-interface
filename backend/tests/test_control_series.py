"""control.csv → plottable series aligned to the run timeline by frame_id."""

from __future__ import annotations

from flir_research_interface.analysis.control_series import (
    control_series_from_rows,
    parse_control_csv,
)

FRAME_T = {100: 0.0, 102: 0.5, 104: 1.0}  # frame_id → relative seconds


def test_series_from_event_rows_maps_and_extracts_numeric_columns() -> None:
    # events.json rows: values are already floats/None (not strings), frame_id stamped by recorder
    rows = [
        {"type": "control", "frame_id": 100, "forward_w": 15.4, "measured_c": 20.0, "roi": "x"},
        {"type": "control", "frame_id": 102, "forward_w": 120.0, "measured_c": 80.0},
        {"type": "control", "frame_id": 104, "forward_w": None, "measured_c": 150.0},
    ]
    s = control_series_from_rows(rows, FRAME_T)
    assert s["t_s"] == [0.0, 0.5, 1.0]
    assert s["forward_w"] == [15.4, 120.0, None]  # gap stays a break
    assert s["measured_c"] == [20.0, 80.0, 150.0]
    assert "roi" not in s


def test_maps_rows_to_relative_time_by_frame_id() -> None:
    csv_text = (
        "frame_id,t_utc,ts,setpoint_c,measured_c,forward_w,roi\n"
        "100,x,x,185,20.0,15.4,circle_medium_small\n"
        "102,x,x,185,80.0,120.0,circle_medium_small\n"
        "104,x,x,185,150.0,135.7,circle_medium_small\n"
    )
    s = parse_control_csv(csv_text, FRAME_T)
    assert s["t_s"] == [0.0, 0.5, 1.0]
    assert s["forward_w"] == [15.4, 120.0, 135.7]  # RF power tracked across the run, not just start
    assert s["measured_c"] == [20.0, 80.0, 150.0]
    assert "roi" not in s  # labels are not series


def test_skips_rows_without_a_known_frame_and_blanks_become_none() -> None:
    csv_text = (
        "frame_id,forward_w\n"
        ",50.0\n"            # no frame_id (pre-record) → dropped
        "999,60.0\n"          # frame not in timeline → dropped
        "102,\n"              # blank power → None (a gap, not a zero)
    )
    s = parse_control_csv(csv_text, FRAME_T)
    assert s["t_s"] == [0.5]
    assert s["forward_w"] == [None]
