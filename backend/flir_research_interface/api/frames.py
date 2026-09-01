"""Wire format for live frames over WebSocket.

Message = 4-byte big-endian header length | UTF-8 JSON header | raw counts (uint16, little
endian, row-major). The header carries the FLIR conversion rule (``kelvin_per_count``,
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
        header["kelvin_per_count"] = k
        c = counts_to_celsius(frame.counts, IRFormat(frame.ir_format))
        header["min_c"] = float(c.min())
        header["max_c"] = float(c.max())
        header["mean_c"] = float(c.mean())
        header["center_c"] = float(c[h // 2, w // 2])
    if stats:
        for key in ("camera_fps", "viz_dropped", "frames_received", "state"):
            if key in stats:
                header[key] = stats[key]
    return header


def encode_frame_message(frame: Frame, stats: dict[str, Any] | None = None) -> bytes:
    header = json.dumps(frame_header(frame, stats)).encode("utf-8")
    payload = np.ascontiguousarray(frame.counts, dtype="<u2").tobytes()
    return struct.pack(">I", len(header)) + header + payload


def decode_frame_message(msg: bytes) -> tuple[dict[str, Any], npt.NDArray[np.uint16]]:
    (n,) = struct.unpack(">I", msg[:4])
    header = json.loads(msg[4 : 4 + n].decode("utf-8"))
    data = np.frombuffer(msg[4 + n :], dtype="<u2").reshape(header["height"], header["width"])
    return header, data.astype(np.uint16, copy=False)


__all__ = ["decode_frame_message", "encode_frame_message", "frame_header"]
