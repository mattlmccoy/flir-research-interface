"""The visible recorder stamps each segment's first-frame host arrival, not just the ffmpeg launch.

ffmpeg writes ``-progress`` blocks to stdout; with ``-use_wallclock_as_timestamps`` a block read
at host time H with ``out_time_us`` = T means the first packet arrived at about H - T, and a live
stream can only make that later (reporting delay), so the minimum over the run is the estimate.
Checked with a live local source and a known injected connect delay (0.5, 3, 8 s): the estimate
landed within 4 ms of the true first byte, the launch time 0.7-8.2 s early. The progress lines
below are the exact format of ffmpeg 6.1.6 (the recorder's binary), captured 2026-09-30.
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from typing import Any

import pytest

from flir_research_interface.playback.visible_timing import thermal_segments
from flir_research_interface.visible.progress import ProgressClock
from flir_research_interface.visible.recorder import VisibleRecorder, ffmpeg_command

BLOCK_BEFORE_FIRST_PACKET = [
    "frame=0",
    "fps=0.00",
    "stream_0_0_q=0.0",
    "bitrate=N/A",
    "total_size=0",
    "out_time_us=N/A",
    "out_time_ms=N/A",
    "out_time=N/A",
    "dup_frames=0",
    "drop_frames=0",
    "speed=N/A",
    "progress=continue",
]


def _block(out_time_us: int, progress: str = "continue") -> list[str]:
    return [
        "frame=12",
        "fps=11.8",
        "stream_0_0_q=-1.0",
        "bitrate=2261.4kbits/s",
        "total_size=303152",
        f"out_time_us={out_time_us}",
        f"out_time_ms={out_time_us}",
        "out_time=00:00:01.072989",
        "dup_frames=0",
        "drop_frames=0",
        "speed=0.998x",
        f"progress={progress}",
    ]


def test_command_reports_progress_on_stdout(tmp_path: Path) -> None:
    out = tmp_path / "visible.mp4"
    cmd = ffmpeg_command("/opt/ffmpeg", "rtsp://h/avc/ch1", out)
    assert cmd[cmd.index("-progress") + 1] == "pipe:1"
    assert cmd[cmd.index("-stats_period") + 1] == "0.5"
    assert cmd[-1] == str(out)


def test_no_estimate_before_the_first_packet() -> None:
    clock = ProgressClock()
    for line in BLOCK_BEFORE_FIRST_PACKET:
        clock.feed(line, 10_000_000_000)
    assert clock.first_frame_host_ns is None and clock.samples == 0


def test_first_frame_is_the_earliest_host_minus_out_time() -> None:
    clock = ProgressClock()
    for line in _block(1_072_989):  # read at 10.0 s: first packet at <= 8.927011 s
        clock.feed(line, 10_000_000_000)
    for line in _block(1_621_000):  # read later with less reporting delay: 8.879 s
        clock.feed(line, 10_500_000_000)
    for line in _block(2_197_956, "end"):  # a slow read never moves the estimate later
        clock.feed(line, 12_000_000_000)
    assert clock.first_frame_host_ns == 8_879_000_000
    assert clock.samples == 3


class _ProgressProc:
    """A finished ffmpeg whose stdout holds progress blocks (FakeProc-compatible surface)."""

    stdout_lines: list[str] = []
    instances: list[_ProgressProc] = []

    def __init__(self, args: list[str], **kwargs: Any) -> None:
        self.args, self.kwargs = args, kwargs
        self.returncode: int | None = None
        self.out = Path(args[-1])
        self.stdout = io.BytesIO("".join(f"{s}\n" for s in self.stdout_lines).encode())
        self.stdin = io.BytesIO()
        _ProgressProc.instances.append(self)

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            self.out.write_bytes(b"\x00\x00\x00\x1cftypisom" + b"x" * 100)
            self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9


def test_recorder_stores_the_first_frame_host_time_per_segment(tmp_path: Path) -> None:
    _ProgressProc.stdout_lines = [
        *BLOCK_BEFORE_FIRST_PACKET,
        *_block(500_000),
        *_block(1_600_000, "end"),
    ]
    reads = iter([10_000_000_000, 11_000_000_000, 12_000_000_000])
    rec = VisibleRecorder(
        ffmpeg="/opt/ffmpeg",
        url="rtsp://h/avc/ch1",
        popen=_ProgressProc,
        probe=None,
        watch_interval_s=None,
        wall_clock=lambda: next(reads),
    )
    rec.start(tmp_path)
    info = rec.stop()
    assert _ProgressProc.instances[-1].kwargs["stdout"] == subprocess.PIPE
    seg = info["segments"][0]
    assert seg["first_frame_host_ns"] == 10_400_000_000  # min(11.0 - 0.5, 12.0 - 1.6) s
    assert seg["first_frame_samples"] == 2


def test_segment_without_progress_has_no_first_frame_stamp(tmp_path: Path) -> None:
    _ProgressProc.stdout_lines = list(BLOCK_BEFORE_FIRST_PACKET)
    rec = VisibleRecorder(
        ffmpeg="/opt/ffmpeg",
        url="rtsp://h/avc/ch1",
        popen=_ProgressProc,
        probe=None,
        watch_interval_s=None,
    )
    rec.start(tmp_path)
    seg = rec.stop()["segments"][0]
    assert seg["first_frame_host_ns"] is None and seg["first_frame_samples"] == 0


def test_timeline_prefers_the_first_frame_stamp_over_the_launch() -> None:
    vis = {
        "file": "visible.mp4",
        "segments": [
            {
                "index": 0,
                "file": "visible.mp4",
                "started_host_ns": 10_000_000_000,
                "first_frame_host_ns": 11_480_000_000,
                "duration_s": 60.0,
            }
        ],
    }
    [seg] = thermal_segments(vis, 6_000_000_000)
    assert seg["t_start_s"] == pytest.approx(5.48)
    assert seg["anchor"] == "first_frame"
    vis["segments"][0]["first_frame_host_ns"] = None  # recorded before this change
    [seg] = thermal_segments(vis, 6_000_000_000)
    assert seg["t_start_s"] == pytest.approx(4.0)
    assert seg["anchor"] == "launch"
