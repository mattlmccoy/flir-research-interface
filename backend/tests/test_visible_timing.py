"""Placing the recorded visible video on the thermal time axis.

Values are captured from real runs on the FLIR SSD (visible.json + thermal.zarr host_timestamp_ns):
20260928_193907_Run (visible opened 24.15 s after thermal frame 0: pre-trigger + 3 failed RTSP
opens), 20260930_143846_Run (4.0 s of pre-trigger) and 20260911_150811_60minrun (made before
segments existed). Before this fix playback assumed visible t=0 == thermal t=0.
"""

from __future__ import annotations

import pytest

from flir_research_interface.playback.visible_timing import FRAME0_SKIP_S, thermal_segments

RUN_193907 = {
    "file": "visible.mp4",
    "started_host_ns": 1790638747423531000,  # first (failed) launch
    "stopped_host_ns": 1790639011605520000,
    "duration_s": 231.877411,
    "segments": [
        {
            "index": 0,
            "file": "visible.mp4",
            "started_host_ns": 1790638767508643000,  # the launch that produced the file
            "stopped_host_ns": 1790639011605520000,
            "duration_s": 231.877411,
            "offset_s": 0.0,
        }
    ],
}
HOST_T0_193907 = 1790638743355263000

LEGACY_60MIN = {  # visible.json from before segments (2026-09-11)
    "file": "visible.mp4",
    "started_host_ns": 1789153692028507000,
    "stopped_host_ns": 1789153980577121000,
    "duration_s": 287.226311,
}
HOST_T0_60MIN = 1789153692034104000


def test_segment_starts_where_its_launch_falls_on_the_thermal_clock() -> None:
    [seg] = thermal_segments(RUN_193907, HOST_T0_193907)
    assert seg["index"] == 0 and seg["file"] == "visible.mp4"
    assert seg["t_start_s"] == pytest.approx(24.153380)
    assert seg["duration_s"] == pytest.approx(231.877411)


def test_split_recording_places_every_segment_by_its_own_launch() -> None:
    vis = {
        "segments": [
            {
                "index": 0,
                "file": "visible.mp4",
                "started_host_ns": 10_000_000_000,
                "duration_s": 77.0,
                "offset_s": 0.0,
            },
            {
                "index": 1,
                "file": "visible_001.mp4",
                "started_host_ns": 105_000_000_000,
                "duration_s": 160.0,
                "offset_s": 95.0,
            },
        ]
    }
    segs = thermal_segments(vis, 6_000_000_000)
    assert [s["t_start_s"] for s in segs] == pytest.approx([4.0, 99.0])


def test_recording_made_before_segments_is_one_segment_from_its_start() -> None:
    [seg] = thermal_segments(LEGACY_60MIN, HOST_T0_60MIN)
    assert seg["index"] == 0 and seg["file"] == "visible.mp4"
    assert seg["t_start_s"] == pytest.approx(-0.005597)
    assert seg["duration_s"] == pytest.approx(287.226311)


def test_without_thermal_frames_segments_keep_their_relative_offsets() -> None:
    [seg] = thermal_segments(RUN_193907, None)
    assert seg["t_start_s"] == 0.0


def test_no_visible_video_has_no_segments() -> None:
    assert thermal_segments(None, HOST_T0_193907) == []
    assert thermal_segments({"file": None, "error": "ffmpeg missing"}, HOST_T0_193907) == []


def test_first_frame_skip_is_past_the_torn_keyframe_split() -> None:
    """Frame 0 is sometimes torn and the video decodes clean from 0.07 s on (7 of 18 runs, likely a
    split opening keyframe, unverified). Shown video never starts before this."""
    assert 0.07 < FRAME0_SKIP_S <= 0.25
