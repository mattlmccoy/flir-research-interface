"""Where the recorded visible video sits on the thermal time axis.

Thermal playback time is seconds after thermal frame 0. Thermal frames carry the host time they
arrived (``host_timestamp_ns``). A visible segment recorded after 2026-09-30 also carries the host
arrival of its first frame (``first_frame_host_ns``, from ffmpeg -progress; see
visible/progress.py); older ones only the ffmpeg launch (``started_host_ns``), which precedes the
first frame by the RTSP connect time (~1.5 s on 2026-09-30 runs). A segment starts ``t_start_s`` =
(that host time - thermal frame 0 arrival) into the thermal axis; ``anchor`` says which was used.
What neither removes is the camera's own encode + network latency before arrival.

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
        first = seg.get("first_frame_host_ns")
        started = first if first is not None else seg.get("started_host_ns")
        if thermal_host_t0_ns is not None and started is not None:
            t_start = (int(started) - int(thermal_host_t0_ns)) / 1e9
            anchor = "first_frame" if first is not None else "launch"
        else:
            t_start = float(seg.get("offset_s") or 0.0)
            anchor = "relative"
        out.append(
            {
                "index": int(seg.get("index", i)),
                "file": str(seg["file"]),
                "t_start_s": t_start,
                "duration_s": seg.get("duration_s"),
                "anchor": anchor,
            }
        )
    return out


__all__ = ["FRAME0_SKIP_S", "thermal_segments"]
