"""Stream-stall rule: the camera delivered no new frame for longer than a threshold.

One rule, used by the recorder for gaps between received frames (checked on arrival) and for the
tail between the last received frame and the stop (checked at finalization). Times are host
wall-clock nanoseconds (``time.time_ns``), the clock Spinnaker frames are stamped with on arrival.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

DEFAULT_STALL_S = 2.0


def iso_utc(t_ns: int) -> str:
    """ISO-8601 UTC with microseconds, the format of ``datetime.now(timezone.utc).isoformat()``."""
    secs, rem = divmod(int(t_ns), 1_000_000_000)
    return datetime.fromtimestamp(secs, timezone.utc).replace(microsecond=rem // 1000).isoformat()


def stream_stall(
    prev_ns: int, now_ns: int, threshold_s: float, *, after_frame_id: int | None
) -> dict[str, Any] | None:
    """The stall record for a frame-less span ``prev_ns -> now_ns``, or None if within threshold.

    ``after_frame_id`` is the last frame received before the span (None: none received yet).
    """
    gap_s = (now_ns - prev_ns) / 1e9
    if gap_s <= threshold_s:
        return None
    return {
        "after_frame_id": after_frame_id,
        "start_utc": iso_utc(prev_ns),
        "end_utc": iso_utc(now_ns),
        "duration_s": round(gap_s, 6),
    }


__all__ = ["DEFAULT_STALL_S", "iso_utc", "stream_stall"]
