"""Where the recorded visible video sits on the thermal time axis.

Thermal playback time is seconds after thermal frame 0. Each visible segment carries the host
wall-clock time its ffmpeg was launched (``started_host_ns``), and thermal frames carry the host
time they arrived (``host_timestamp_ns``), so a segment starts ``t_start_s`` =
(launch - thermal frame 0 arrival) into the thermal axis. The launch precedes the first video frame
by the RTSP connect time (not recorded; ~1.5 s on 2026-09-30 runs), so the video may still trail by
that much. Pre-trigger frames and failed RTSP opens no longer shift it by seconds.

Frame 0 of a file is sometimes torn (vertically wrapped; 7 of 18 runs up to 2026-09-30). Those
files all have an unusually large (~45 KB) second packet within 0.07 s, likely the opening
keyframe split in two (unverified); from the next frame the video decodes clean.
Nothing shows a segment's first ``FRAME0_SKIP_S``.
"""

from __future__ import annotations

from typing import Any

FRAME0_SKIP_S = 0.25


def thermal_segments(
    vis: dict[str, Any] | None, thermal_host_t0_ns: int | None
) -> list[dict[str, Any]]:
    """Visible segments as ``{index, file, t_start_s, duration_s}`` on the thermal time axis.

    A recording made before segments (no ``segments`` in visible.json) is one segment from its
    top-level ``started_host_ns``. Without a thermal frame to anchor to, segments keep their
    offsets relative to the first one (the previous behaviour).
    """
    if not vis or not (vis.get("segments") or vis.get("file")):
        return []
    segs = vis.get("segments") or [
        {
            "index": 0,
            "file": vis["file"],
            "started_host_ns": vis.get("started_host_ns"),
            "duration_s": vis.get("duration_s"),
            "offset_s": 0.0,
        }
    ]
    out = []
    for i, seg in enumerate(segs):
        started = seg.get("started_host_ns")
        if thermal_host_t0_ns is not None and started is not None:
            t_start = (int(started) - int(thermal_host_t0_ns)) / 1e9
        else:
            t_start = float(seg.get("offset_s") or 0.0)
        out.append(
            {
                "index": int(seg.get("index", i)),
                "file": str(seg["file"]),
                "t_start_s": t_start,
                "duration_s": seg.get("duration_s"),
            }
        )
    return out


__all__ = ["FRAME0_SKIP_S", "thermal_segments"]
