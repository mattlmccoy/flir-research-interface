"""Ordering of camera frame ids across the 16-bit wrap.

The FLIR A70 reports the GigE Vision block id as ``frame_id``: 16 bits, wrapping 65535 -> 1 (0 is
reserved), i.e. every ~36 min at 30 fps. A reconnect also restarts it at 1. A backwards step is
read as a wrap only when it lands within ``WRAP_WINDOW`` ids past 65535; any other backwards step
is a counter reset, which says nothing about lost frames.
"""

from __future__ import annotations

FRAME_ID_MAX = 0xFFFF
WRAP_WINDOW = 4096
"""Largest step (in frames) still read as a wrap rather than a reset: ~2 min at 30 fps."""


def frame_id_step(prev: int, cur: int) -> int | None:
    """Frames from ``prev`` to ``cur`` (1 = consecutive), or None if ``cur`` does not follow it."""
    if cur > prev:
        return cur - prev
    if prev > FRAME_ID_MAX:  # a counter wider than 16 bits (simulated camera) never wraps here
        return None
    step = (FRAME_ID_MAX - prev) + max(cur, 1)  # id 0 is skipped on the wrap
    return step if 0 < step <= WRAP_WINDOW else None


def frames_missing(prev: int, cur: int) -> int:
    """Frames lost between consecutive received ids; 0 across a reset or a repeat."""
    step = frame_id_step(prev, cur)
    return step - 1 if step is not None else 0


__all__ = ["FRAME_ID_MAX", "WRAP_WINDOW", "frame_id_step", "frames_missing"]
