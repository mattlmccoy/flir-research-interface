"""ROI time series over a whole recording.

Reads the Zarr store in batches through ``ExperimentReader`` (read-only) and evaluates each
ROI on every frame. Values are °C when the recording is temperature-linear; otherwise raw
counts (``units`` says which). Pixels outside the image or NaN yield ``None`` so a bad ROI
produces a visible gap instead of an error.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np

from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.radiometry.temperature_linear import IRFormat, counts_to_celsius

MAX_ROIS = 32


def _int(v: Any, name: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int | float) or not float(v).is_integer():
        raise ValueError(f"{name} must be an integer")
    return int(v)


def parse_rois(raw: str) -> list[dict[str, Any]]:
    """Validate the JSON ROI list sent by the client (spots and half-open rectangles)."""
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"rois is not valid JSON: {exc}") from exc
    if not isinstance(items, list):
        raise ValueError("rois must be a JSON list")
    if len(items) > MAX_ROIS:
        raise ValueError(f"at most {MAX_ROIS} rois")
    out: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            raise ValueError("each roi must be an object")
        kind = it.get("kind")
        rid = _int(it.get("id"), "id")
        if kind == "spot":
            x, y = _int(it.get("x"), "x"), _int(it.get("y"), "y")
            out.append({"id": rid, "kind": "spot", "x": x, "y": y})
        elif kind == "rect":
            r = {k: _int(it.get(k), k) for k in ("x0", "y0", "x1", "y1")}
            if r["x1"] <= r["x0"] or r["y1"] <= r["y0"]:
                raise ValueError("rect must have x1 > x0 and y1 > y0")
            out.append({"id": rid, "kind": "rect", **r})
        elif kind == "circle":
            cx, cy = _int(it.get("cx"), "cx"), _int(it.get("cy"), "cy")
            radius = it.get("r")
            if isinstance(radius, bool) or not isinstance(radius, int | float) or radius < 1:
                raise ValueError("circle r must be a number >= 1")
            out.append({"id": rid, "kind": "circle", "cx": cx, "cy": cy, "r": float(radius)})
        elif kind == "line":
            r = {k: _int(it.get(k), k) for k in ("x0", "y0", "x1", "y1")}
            if (r["x0"], r["y0"]) == (r["x1"], r["y1"]):
                raise ValueError("line endpoints must differ")
            out.append({"id": rid, "kind": "line", **r})
        elif kind == "polyline":
            pts = it.get("points")
            if not isinstance(pts, list) or len(pts) < 2:
                raise ValueError("polyline needs at least 2 points")
            points = []
            for p in pts:
                if not isinstance(p, list | tuple) or len(p) != 2:
                    raise ValueError("polyline points must be [x, y] pairs")
                points.append([_int(p[0], "x"), _int(p[1], "y")])
            out.append({"id": rid, "kind": "polyline", "points": points})
        else:
            raise ValueError(f"unknown roi kind {kind!r}")
    return out


def _line_pixels(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    """Bresenham, both endpoints inclusive (mirrors frontend lib/roi.ts linePixels)."""
    out: list[tuple[int, int]] = []
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err, x, y = dx + dy, x0, y0
    while True:
        out.append((x, y))
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy
    return out


def roi_index(roi: dict[str, Any], w: int, h: int) -> tuple[np.ndarray, np.ndarray]:
    """(ys, xs) of the pixels a non-rect ROI covers inside a w×h image (no duplicates)."""
    kind = roi["kind"]
    if kind == "spot":
        pts = [(roi["x"], roi["y"])]
    elif kind == "circle":
        cx, cy, r = roi["cx"], roi["cy"], roi["r"]
        ys, xs = np.mgrid[max(0, int(np.floor(cy - r))) : min(h, int(np.ceil(cy + r)) + 1),
                          max(0, int(np.floor(cx - r))) : min(w, int(np.ceil(cx + r)) + 1)]
        m = (xs - cx) ** 2 + (ys - cy) ** 2 <= r * r
        return ys[m], xs[m]
    elif kind == "line":
        pts = _line_pixels(roi["x0"], roi["y0"], roi["x1"], roi["y1"])
    else:  # polyline
        seen: set[tuple[int, int]] = set()
        pts = []
        p = roi["points"]
        for (ax, ay), (bx, by) in zip(p[:-1], p[1:], strict=True):
            for q in _line_pixels(ax, ay, bx, by):
                if q not in seen:
                    seen.add(q)
                    pts.append(q)
    inside = [(x, y) for x, y in pts if 0 <= x < w and 0 <= y < h]
    ys_ = np.array([y for _, y in inside], dtype=np.intp)
    xs_ = np.array([x for x, _ in inside], dtype=np.intp)
    return ys_, xs_


def _clean(a: np.ndarray) -> list[float | None]:
    return [None if not math.isfinite(float(v)) else float(v) for v in a]


def roi_series(
    reader: ExperimentReader, rois: list[dict[str, Any]], *, batch: int = 64
) -> dict[str, Any]:
    """Per-frame ROI values for every frame of ``reader``.

    Spots return ``value``; rectangles return ``min``/``max``/``mean``. Batches of frames are
    read at once so the store is touched chunk-wise, never frame-by-frame.
    """
    n = reader.n_frames
    fmt: IRFormat | None
    try:
        fmt = IRFormat(reader.ir_format or "")
        if fmt is IRFormat.RADIOMETRIC:
            fmt = None
    except ValueError:
        fmt = None
    acc: dict[int, dict[str, np.ndarray]] = {}
    for r in rois:
        keys = ("value",) if r["kind"] == "spot" else ("min", "max", "mean")
        acc[r["id"]] = {k: np.full(n, np.nan) for k in keys}
    for start in range(0, n, max(1, batch)):
        stop = min(n, start + batch)
        block = reader.counts_block(start, stop)
        field = counts_to_celsius(block, fmt) if fmt is not None else block.astype(np.float64)
        _, h, w = field.shape
        for r in rois:
            dst = acc[r["id"]]
            if r["kind"] == "spot":
                if 0 <= r["x"] < w and 0 <= r["y"] < h:
                    dst["value"][start:stop] = field[:, r["y"], r["x"]]
                continue
            if r["kind"] == "rect":
                x0, y0 = max(0, r["x0"]), max(0, r["y0"])
                x1, y1 = min(w, r["x1"]), min(h, r["y1"])
                if x1 <= x0 or y1 <= y0:
                    continue
                sub = field[:, y0:y1, x0:x1].reshape(stop - start, -1)
            else:
                ys, xs = roi_index(r, w, h)
                if len(ys) == 0:
                    continue
                sub = field[:, ys, xs]
            with np.errstate(all="ignore"):
                dst["min"][start:stop] = np.nanmin(sub, axis=1)
                dst["max"][start:stop] = np.nanmax(sub, axis=1)
                dst["mean"][start:stop] = np.nanmean(sub, axis=1)
    tl = reader.timeline()
    return {
        "units": "celsius" if fmt is not None else "counts",
        "t_s": tl["t_s"],
        "frame_id": tl["frame_id"],
        "series": {str(rid): {k: _clean(v) for k, v in d.items()} for rid, d in acc.items()},
    }


__all__ = ["MAX_ROIS", "parse_rois", "roi_index", "roi_series"]
