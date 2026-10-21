"""Wire format for live frames over WebSocket.

Message = 4-byte big-endian header length | UTF-8 JSON header | raw counts (uint16, little
endian, row-major). On request (``rf_notch``) the header carries ``display: {rf_notch: info,
counts: true}`` and a second uint16 array follows: the same frame with the RF banding removed, for
display only (ROI readouts and stats keep using the raw counts, which always come first).
The header carries the FLIR conversion rule (``kelvin_per_count``,
``kelvin_offset``) so the client derives °C itself; the server never sends colorized pixels.
Statistics in the header are computed server-side from the same counts.
"""

from __future__ import annotations

import json
import struct
from typing import Any

import numpy as np
import numpy.typing as npt

from flir_research_interface.camera.base import Frame
from flir_research_interface.radiometry.temperature_linear import (
    KELVIN_OFFSET,
    IRFormat,
    counts_to_celsius,
    kelvin_per_count,
)


def _finite(v: Any) -> float | None:
    return float(v) if np.isfinite(v) else None


def frame_header(frame: Frame, stats: dict[str, Any] | None = None) -> dict[str, Any]:
    h, w = frame.counts.shape
    header: dict[str, Any] = {
        "type": "frame",
        "frame_id": frame.frame_id,
        "device_timestamp_ns": frame.device_timestamp_ns,
        "host_timestamp_ns": frame.host_timestamp_ns,
        "width": int(w),
        "height": int(h),
        "dtype": "uint16",
        "byte_order": "little",
        "pixel_format": frame.pixel_format,
        "ir_format": frame.ir_format,
        "kelvin_per_count": None,
        "kelvin_offset": KELVIN_OFFSET,
        "min_c": None,
        "max_c": None,
        "mean_c": None,
        "center_c": None,
        "incomplete": frame.incomplete,
    }
    try:
        fmt = IRFormat(frame.ir_format)
        k = kelvin_per_count(fmt)
    except ValueError:
        k = None
    if k is not None:
        from flir_research_interface.radiometry.overrange import over_range_mask

        header["kelvin_per_count"] = k
        c = counts_to_celsius(frame.counts, IRFormat(frame.ir_format))
        # over-range (saturated / wrapped) pixels carry no valid temperature — exclude them from
        # the whole-frame stats so a wrapped hot-spot can't drag min_c to an impossible value
        over = over_range_mask(frame.counts)
        valid = c if over is None else np.where(over, np.nan, c)
        header["min_c"] = _finite(np.nanmin(valid))
        header["max_c"] = _finite(np.nanmax(valid))
        header["mean_c"] = _finite(np.nanmean(valid))
        center = c[h // 2, w // 2]
        header["center_c"] = None if (over is not None and over[h // 2, w // 2]) else float(center)
        if over is not None:
            header["over_range"] = int(over.sum())
    if stats:
        for key in ("camera_fps", "viz_dropped", "frames_received", "state"):
            if key in stats:
                header[key] = stats[key]
    return header


def encode_frame_message(
    frame: Frame,
    stats: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
    *,
    rf_notch: bool = False,
) -> bytes:
    hdr = frame_header(frame, stats)
    if extra:
        hdr.update(extra)
    payload = np.ascontiguousarray(frame.counts, dtype="<u2").tobytes()
    if rf_notch:
        from flir_research_interface.analysis.rf_notch import rf_notch as remove_banding

        display, info = remove_banding(frame.counts, hdr.get("kelvin_per_count"))
        hdr["display"] = {"rf_notch": info, "counts": True}
        payload += np.ascontiguousarray(display, dtype="<u2").tobytes()
    header = json.dumps(hdr).encode("utf-8")
    return struct.pack(">I", len(header)) + header + payload


def decode_frame_message(msg: bytes) -> tuple[dict[str, Any], npt.NDArray[np.uint16]]:
    (n,) = struct.unpack(">I", msg[:4])
    header = json.loads(msg[4 : 4 + n].decode("utf-8"))
    size = header["height"] * header["width"]
    flat = np.frombuffer(msg[4 + n :], dtype="<u2", count=size)
    return header, flat.reshape(header["height"], header["width"]).astype(np.uint16, copy=False)


def decode_display_counts(msg: bytes) -> npt.NDArray[np.uint16] | None:
    """The display copy (RF banding removed) when the message carries one, else None."""
    (n,) = struct.unpack(">I", msg[:4])
    header = json.loads(msg[4 : 4 + n].decode("utf-8"))
    if not (header.get("display") or {}).get("counts"):
        return None
    h, w = header["height"], header["width"]
    raw = np.frombuffer(msg[4 + n :], dtype="<u2")
    return raw[h * w : 2 * h * w].reshape(h, w).astype(np.uint16, copy=False)


__all__ = ["decode_display_counts", "decode_frame_message", "encode_frame_message", "frame_header"]
