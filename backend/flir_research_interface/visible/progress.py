"""First-frame host time of a visible segment, from ffmpeg's ``-progress`` output.

With ``-use_wallclock_as_timestamps 1`` the output timestamps are the packets' host arrival times,
shifted so the first packet is 0. A progress block read at host time H reporting ``out_time_us`` =
T therefore puts the first packet's arrival at about H - T; delay in writing or reading the block
only makes that later, so the minimum over the segment is the estimate (within one frame, since
out_time may include the last packet's duration). The ffmpeg launch time alone misses the RTSP
connect time, measured at 0.7-8.2 s with a local source and injected delays.
"""

from __future__ import annotations

KEY = "out_time_us="


class ProgressClock:
    """Feed ffmpeg ``-progress`` lines with the host time each was read."""

    def __init__(self) -> None:
        self.first_frame_host_ns: int | None = None
        self.samples = 0

    def feed(self, line: str, host_ns: int) -> None:
        if not line.startswith(KEY):
            return
        value = line[len(KEY) :].strip()
        if not value.isdigit():  # "N/A" until the first packet is written
            return
        estimate = host_ns - int(value) * 1000
        self.samples += 1
        if self.first_frame_host_ns is None or estimate < self.first_frame_host_ns:
            self.first_frame_host_ns = estimate


__all__ = ["ProgressClock"]
