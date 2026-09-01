"""Validation mode CLI (``fri-live``): stream frames and print/log temperatures for known pixels.

This is the Milestone-2 tool used to compare this application against FLIR Research Studio
(docs/validation.md). It converts counts with the FLIR-documented temperature-linear rule only,
writes one CSV row per frame, and prints a summary. It never changes object parameters or the
measurement case; it does set ``IRFormat``/``PixelFormat`` through the backend (restored on exit).
"""

from __future__ import annotations

import argparse
import csv
import logging
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from flir_research_interface.analysis.stats import (
    RectangleRoi,
    Spot,
    frame_stats,
    roi_stats,
    spot_value,
)
from flir_research_interface.camera import create_backend
from flir_research_interface.camera.base import Frame
from flir_research_interface.camera.simulated import HotspotRampScene
from flir_research_interface.radiometry.temperature_linear import IRFormat, counts_to_celsius

logger = logging.getLogger(__name__)


def parse_spot(text: str) -> Spot:
    x, y = (int(v) for v in text.split(","))
    return Spot(x=x, y=y)


def parse_roi(text: str) -> RectangleRoi:
    x0, y0, x1, y1 = (int(v) for v in text.split(","))
    return RectangleRoi(x0=x0, y0=y0, x1=x1, y1=y1)


def _spot_key(i: int, s: Spot) -> str:
    return f"spot{i}_x{s.x}_y{s.y}_C"


def csv_header(*, spots: Sequence[Spot], rois: Sequence[RectangleRoi]) -> list[str]:
    hdr = [
        "time_s",
        "frame_id",
        "device_timestamp_ns",
        "host_timestamp_ns",
        "center_C",
        "frame_min_C",
        "frame_max_C",
        "frame_mean_C",
        "frame_std_C",
    ]
    hdr += [_spot_key(i, s) for i, s in enumerate(spots, 1)]
    for i, _ in enumerate(rois, 1):
        hdr += [f"roi{i}_mean_C", f"roi{i}_min_C", f"roi{i}_max_C", f"roi{i}_std_C"]
    return hdr


def frame_row(
    frame: Frame, *, t0_ns: int, spots: Sequence[Spot], rois: Sequence[RectangleRoi]
) -> dict[str, Any]:
    """One CSV row: temperatures derived from counts with the frame's own IRFormat."""
    celsius = counts_to_celsius(frame.counts, IRFormat(frame.ir_format))
    fs = frame_stats(celsius)
    h, w = celsius.shape
    row: dict[str, Any] = {
        "time_s": (frame.device_timestamp_ns - t0_ns) / 1e9,
        "frame_id": frame.frame_id,
        "device_timestamp_ns": frame.device_timestamp_ns,
        "host_timestamp_ns": frame.host_timestamp_ns,
        "center_C": float(celsius[h // 2, w // 2]),
        "frame_min_C": fs["min"],
        "frame_max_C": fs["max"],
        "frame_mean_C": fs["mean"],
        "frame_std_C": fs["std"],
    }
    for i, s in enumerate(spots, 1):
        row[_spot_key(i, s)] = spot_value(celsius, s)
    for i, r in enumerate(rois, 1):
        rs = roi_stats(celsius, r)
        row[f"roi{i}_mean_C"] = rs["mean"]
        row[f"roi{i}_min_C"] = rs["min"]
        row[f"roi{i}_max_C"] = rs["max"]
        row[f"roi{i}_std_C"] = rs["std"]
    return row


def summarize_rows(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"frames": 0}
    ts = np.array([r["device_timestamp_ns"] for r in rows], dtype=np.int64)
    ids = np.array([r["frame_id"] for r in rows], dtype=np.int64)
    duration_s = float((ts[-1] - ts[0]) / 1e9)
    center = np.array([r["center_C"] for r in rows], dtype=np.float64)
    return {
        "frames": len(rows),
        "duration_s": duration_s,
        "fps_from_device_timestamps": (len(rows) - 1) / duration_s if duration_s > 0 else None,
        "frame_id_gaps": int(np.sum(np.diff(ids) - 1)) if len(ids) > 1 else 0,
        "center_C_mean": float(center.mean()),
        "center_C_std": float(center.std()),
        "center_C_min": float(center.min()),
        "center_C_max": float(center.max()),
    }


def _write_csv(path: Path, header: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Stream frames and print temperatures for known pixels")
    p.add_argument("--simulated", action="store_true", help="use the simulated camera")
    p.add_argument("--seconds", type=float, default=5.0, help="how long to stream")
    p.add_argument("--spot", action="append", default=[], metavar="X,Y", help="extra spot(s)")
    p.add_argument(
        "--roi", action="append", default=[], metavar="X0,Y0,X1,Y1", help="rectangle ROI(s)"
    )
    p.add_argument("--csv", default=None, help="write per-frame CSV here")
    p.add_argument("--print-every", type=int, default=15, help="print every Nth frame")
    p.add_argument("--resolution", choices=["10mK", "100mK"], default="10mK")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    spots = [parse_spot(s) for s in args.spot]
    rois = [parse_roi(r) for r in args.roi]
    ir = (
        IRFormat.TEMPERATURE_LINEAR_10MK
        if args.resolution == "10mK"
        else IRFormat.TEMPERATURE_LINEAR_100MK
    )

    if args.simulated:
        scene = HotspotRampScene(
            background_c=25.0,
            start_c=25.0,
            end_c=200.0,
            ramp_s=60.0,
            center_xy=(320, 240),
            radius_px=40,
        )
        cam = create_backend("simulated", scene=scene, ir_format=ir, realtime=True)
    else:
        cam = create_backend("spinnaker", ir_format=ir)

    devices = cam.enumerate()
    if not devices:
        print("no camera found (run fri-probe for diagnosis)")
        return 1
    cam.connect(devices[0])
    rows: list[dict[str, Any]] = []
    try:
        info = cam.camera_info()
        print(
            f"Connected: {info.get('model')} serial={info.get('serial')} fw={info.get('firmware')} "
            f"lens={info.get('lens')} ir_format={info.get('ir_format')} case={info.get('active_case')}"
        )
        print("Object parameters:", info.get("object_parameters"))
        header = csv_header(spots=spots, rois=rois)
        t_end = time.monotonic() + args.seconds
        t0_ns: int | None = None
        for frame in cam.frames():
            if t0_ns is None:
                t0_ns = frame.device_timestamp_ns
            row = frame_row(frame, t0_ns=t0_ns, spots=spots, rois=rois)
            rows.append(row)
            if (len(rows) - 1) % args.print_every == 0:
                extras = "  ".join(f"{k}={row[k]:.2f}" for k in header[9:])
                print(
                    f"t={row['time_s']:7.3f}s id={row['frame_id']:<6} center={row['center_C']:7.2f}C "
                    f"min={row['frame_min_C']:7.2f} max={row['frame_max_C']:7.2f} "
                    f"mean={row['frame_mean_C']:7.2f}  {extras}"
                )
            if time.monotonic() >= t_end:
                break
        summary = summarize_rows(rows)
        stats_fn = getattr(cam, "stream_stats", None)
        if callable(stats_fn):
            summary["stream_counters"] = stats_fn()
        print("Summary:", summary)
        if args.csv:
            _write_csv(Path(args.csv), header, rows)
            print(f"CSV written: {args.csv} ({len(rows)} rows)")
    finally:
        cam.disconnect()
    return 0


__all__ = ["csv_header", "frame_row", "main", "parse_roi", "parse_spot", "summarize_rows"]
