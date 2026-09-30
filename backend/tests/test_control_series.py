"""control.csv → plottable series aligned to the run timeline by frame_id."""

from __future__ import annotations

import json
from pathlib import Path

from flir_research_interface.analysis.control_series import (
    control_series_from_rows,
    parse_control_csv,
)

FRAME_T = {"frame_id": [100, 102, 104], "t_s": [0.0, 0.5, 1.0]}  # the run timeline
RESET_FIXTURE = Path(__file__).parent / "fixtures" / "control_reset_20260923_175956.json"


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


def test_samples_land_on_their_own_frame_after_a_camera_reconnect_reuses_ids() -> None:
    # captured: the camera reconnected twice mid-run, so ids 1..71 occur twice in the timeline
    fx = json.loads(RESET_FIXTURE.read_text())
    ids, t = fx["frame_id"], fx["t_s"]
    seg2 = ids.index(1)  # first restart (9177 -> 1)
    seg3 = ids.index(1, seg2 + 1)  # second restart (71 -> 1)

    def at(fid: int, start: int) -> float:
        return float(t[ids.index(fid, start)])

    expected = (
        [at(9177, 0)] * 3
        + [at(19, seg2), at(57, seg2)]
        + [at(71, seg2)] * 15  # stamped with the last frame before the outage
        + [at(20, seg3), at(56, seg3), at(92, seg3)]
    )
    s = control_series_from_rows(fx["control"], {"frame_id": ids, "t_s": t})
    assert s["t_s"] == expected
    assert s["forward_w"] == [c["forward_w"] for c in fx["control"]]


def test_samples_in_a_run_longer_than_one_16_bit_id_cycle_keep_their_order() -> None:
    # synthetic (no captured run exceeds 65535 frames): ids wrap 65535 -> 1 and repeat
    ids = list(range(1, 65536)) * 2
    t = [i / 30 for i in range(len(ids))]
    rows = [{"frame_id": 100, "forward_w": 1.0}, {"frame_id": 50, "forward_w": 2.0}]
    s = control_series_from_rows(rows, {"frame_id": ids, "t_s": t})
    assert s["t_s"] == [t[99], t[65535 + 49]]  # the second sample is in the second cycle
