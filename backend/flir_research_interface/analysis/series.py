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
from flir_research_interface.radiometry.emissivity import Radiometry, recorrect_celsius
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
            spot: dict[str, Any] = {"id": rid, "kind": "spot", "x": x, "y": y}
            box = it.get("box", 1)
            if box not in (1, 3) or isinstance(box, bool):
                raise ValueError("spot box must be 1 or 3")
            if box == 3:
                spot["box"] = 3  # measurement cursor: mean of the 3x3 neighbourhood
            out.append(spot)
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
        elif kind == "ellipse":
            cx, cy = _int(it.get("cx"), "cx"), _int(it.get("cy"), "cy")
            radii: dict[str, float] = {}
            for nm in ("rx", "ry"):
                v = it.get(nm)
                if isinstance(v, bool) or not isinstance(v, int | float) or v < 1:
                    raise ValueError(f"ellipse {nm} must be a number >= 1")
                radii[nm] = float(v)
            out.append({"id": rid, "kind": "ellipse", "cx": cx, "cy": cy, **radii})
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
        elif kind == "polygon":
            pts = it.get("points")
            if not isinstance(pts, list) or len(pts) < 3:
                raise ValueError("polygon needs at least 3 points")
            points = []
            for p in pts:
                if not isinstance(p, list | tuple) or len(p) != 2:
                    raise ValueError("polygon points must be [x, y] pairs")
                points.append([_int(p[0], "x"), _int(p[1], "y")])
            out.append({"id": rid, "kind": "polygon", "points": points})
        else:
            raise ValueError(f"unknown roi kind {kind!r}")
        _optical(it, out[-1])
    return out


def _optical(src: dict[str, Any], dst: dict[str, Any]) -> None:
    """Per-ROI emissivity (0.01..1) and reflected temperature (°C), optional."""
    eps = src.get("emissivity")
    if eps is not None:
        if isinstance(eps, bool) or not isinstance(eps, int | float) or not 0.01 <= eps <= 1.0:
            raise ValueError("emissivity must be a number between 0.01 and 1")
        dst["emissivity"] = float(eps)
    dist = src.get("distance_m")
    if dist is not None:
        if isinstance(dist, bool) or not isinstance(dist, int | float) or dist <= 0:
            raise ValueError("distance_m must be a positive number of metres")
        dst["distance_m"] = float(dist)
    trefl = src.get("reflected_c")
    if trefl is not None:
        if (
            isinstance(trefl, bool)
            or not isinstance(trefl, int | float)
            or not -100 <= trefl <= 2000
        ):
            raise ValueError("reflected_c must be a temperature in °C")
        dst["reflected_c"] = float(trefl)


def roi_field(
    field: np.ndarray, roi: dict[str, Any], cam: dict[str, Any] | None, celsius: bool
) -> np.ndarray:
    """``field`` re-corrected for the ROI's emissivity / reflected temperature when it has one
    and the camera constants are known; otherwise ``field`` unchanged."""
    if not celsius or ("emissivity" not in roi and "reflected_c" not in roi):
        return field
    rad = Radiometry.from_camera(cam)
    if rad is None:
        return field
    rbf, eps_cam, trefl_cam = rad
    eps = float(roi.get("emissivity", eps_cam))
    trefl_k = float(roi["reflected_c"]) + 273.15 if "reflected_c" in roi else trefl_cam
    return recorrect_celsius(
        field, rbf, eps_cam=eps_cam, trefl_cam_k=trefl_cam, eps=eps, trefl_k=trefl_k
    )


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
    pts: list[tuple[int, int]]
    if kind == "spot":
        pts = [(int(roi["x"]), int(roi["y"]))]
    elif kind == "polyline":
        pts = roi["points"]
        seq: list[tuple[int, int]] = []
        for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
            seg = _line_pixels(x0, y0, x1, y1)
            seq.extend(seg[1:] if seq else seg)  # joints once
        keep = [(x, y) for x, y in seq if 0 <= x < w and 0 <= y < h]
        ys_l = np.array([y for _, y in keep], dtype=np.intp)
        xs_l = np.array([x for x, _ in keep], dtype=np.intp)
        return ys_l, xs_l
    elif kind == "ellipse":
        cx, cy, rx, ry = roi["cx"], roi["cy"], roi["rx"], roi["ry"]
        ys, xs = np.mgrid[
            max(0, int(np.floor(cy - ry))) : min(h, int(np.ceil(cy + ry)) + 1),
            max(0, int(np.floor(cx - rx))) : min(w, int(np.ceil(cx + rx)) + 1),
        ]
        m = ((xs - cx) / rx) ** 2 + ((ys - cy) / ry) ** 2 <= 1.0
        return ys[m].astype(np.intp), xs[m].astype(np.intp)
    elif kind == "circle":
        cx, cy, r = roi["cx"], roi["cy"], roi["r"]
        ys, xs = np.mgrid[
            max(0, int(np.floor(cy - r))) : min(h, int(np.ceil(cy + r)) + 1),
            max(0, int(np.floor(cx - r))) : min(w, int(np.ceil(cx + r)) + 1),
        ]
        m = (xs - cx) ** 2 + (ys - cy) ** 2 <= r * r
        return ys[m], xs[m]
    elif kind == "line":
        pts = _line_pixels(roi["x0"], roi["y0"], roi["x1"], roi["y1"])
    else:  # polygon: even-odd interior on pixel centres plus the Bresenham boundary
        p = [(int(x), int(y)) for x, y in roi["points"]]
        n = len(p)
        seen: set[tuple[int, int]] = set()
        pts = []
        for i in range(n):
            (ax, ay), (bx, by) = p[i], p[(i + 1) % n]
            for q in _line_pixels(ax, ay, bx, by):
                if q not in seen:
                    seen.add(q)
                    pts.append(q)
        x_min, x_max = max(0, min(x for x, _ in p)), min(w - 1, max(x for x, _ in p))
        y_min, y_max = max(0, min(y for _, y in p)), min(h - 1, max(y for _, y in p))
        if x_max >= x_min and y_max >= y_min:
            ys_g, xs_g = np.mgrid[y_min : y_max + 1, x_min : x_max + 1]
            mask = np.zeros(ys_g.shape, dtype=bool)
            j = n - 1
            for i in range(n):
                (xi, yi), (xj, yj) = p[i], p[j]
                crosses = (yi > ys_g) != (yj > ys_g)
                with np.errstate(divide="ignore", invalid="ignore"):
                    xcross = (xj - xi) * (ys_g - yi) / (yj - yi) + xi
                mask ^= crosses & (xs_g < xcross)
                j = i
            for y, x in zip(ys_g[mask].tolist(), xs_g[mask].tolist(), strict=True):
                if (x, y) not in seen:
                    seen.add((x, y))
                    pts.append((x, y))
    inside = [(x, y) for x, y in pts if 0 <= x < w and 0 <= y < h]
    ys_ = np.array([y for _, y in inside], dtype=np.intp)
    xs_ = np.array([x for x, _ in inside], dtype=np.intp)
    return ys_, xs_


def _clean(a: np.ndarray) -> list[float | None]:
    return [None if not math.isfinite(float(v)) else float(v) for v in a]


def roi_series(
    reader: ExperimentReader,
    rois: list[dict[str, Any]],
    *,
    batch: int = 64,
    valid_c: tuple[float, float] | None = None,
    stride: int = 1,
) -> dict[str, Any]:
    """Per-frame ROI values for every frame of ``reader``.

    Spots return ``value``; rectangles return ``min``/``max``/``mean``. Batches of frames are
    read at once so the store is touched chunk-wise, never frame-by-frame. ``stride`` keeps every
    Nth frame (for a plot that cannot show more points than pixels); the CSV export uses stride 1.
    """
    stride = max(1, int(stride))
    n = reader.n_frames
    keep = np.arange(0, n, stride)  # frames actually computed
    m = len(keep)
    fmt: IRFormat | None
    try:
        fmt = IRFormat(reader.ir_format or "")
        if fmt is IRFormat.RADIOMETRIC:
            fmt = None
    except ValueError:
        fmt = None
    cam = reader.metadata.get("camera")
    _, h0, w0 = reader.counts_block(0, 1).shape if n else (0, 0, 0)
    acc: dict[int, dict[str, np.ndarray]] = {}
    # Precompute each ROI's pixel index ONCE (geometry is fixed for the run); recomputing the
    # polygon/circle masks per batch was ~2/3 of this function's cost.
    index: dict[int, tuple[np.ndarray, np.ndarray] | None] = {}
    for r in rois:
        keys = ("value",) if r["kind"] == "spot" else ("min", "max", "mean", "std", "n")
        acc[r["id"]] = {k: np.full(m, np.nan) for k in keys}
        if r["kind"] not in ("spot", "rect"):
            ys, xs = roi_index(r, w0, h0)
            index[r["id"]] = (ys, xs) if len(ys) else None
    step = max(1, batch) * stride  # read a wide block, keep every stride-th frame from it
    for start in range(0, n, step):
        stop = min(n, start + step)
        local = np.arange(start, stop, stride) - start  # kept rows within this block
        pos = start // stride  # first strided position this block writes
        block = (
            reader.counts_block(start, stop)[local]
            if stride > 1
            else reader.counts_block(start, stop)
        )
        field0 = counts_to_celsius(block, fmt) if fmt is not None else block.astype(np.float64)
        b, h, w = field0.shape  # b == number of kept frames in this block
        for r in rois:
            field = roi_field(field0, r, cam, fmt is not None)
            if valid_c is not None:  # segmentation: outside the valid range → ignored (NaN)
                lo, hi = valid_c
                field = np.where((field >= lo) & (field <= hi), field, np.nan)
            dst = acc[r["id"]]
            if r["kind"] == "spot":
                if r.get("box") == 3:
                    y0, y1 = max(0, r["y"] - 1), min(h, r["y"] + 2)
                    x0, x1 = max(0, r["x"] - 1), min(w, r["x"] + 2)
                    if y1 > y0 and x1 > x0:
                        with np.errstate(all="ignore"):
                            dst["value"][pos : pos + b] = np.nanmean(
                                field[:, y0:y1, x0:x1].reshape(b, -1), axis=1
                            )
                elif 0 <= r["x"] < w and 0 <= r["y"] < h:
                    dst["value"][pos : pos + b] = field[:, r["y"], r["x"]]
                continue
            if r["kind"] == "rect":
                x0, y0 = max(0, r["x0"]), max(0, r["y0"])
                x1, y1 = min(w, r["x1"]), min(h, r["y1"])
                if x1 <= x0 or y1 <= y0:
                    continue
                sub = field[:, y0:y1, x0:x1].reshape(b, -1)
            else:
                ix = index.get(r["id"])
                if ix is None:
                    continue
                sub = field[:, ix[0], ix[1]]
            with np.errstate(all="ignore"):
                dst["min"][pos : pos + b] = np.nanmin(sub, axis=1)
                dst["max"][pos : pos + b] = np.nanmax(sub, axis=1)
                dst["mean"][pos : pos + b] = np.nanmean(sub, axis=1)
                dst["std"][pos : pos + b] = np.nanstd(sub, axis=1)  # population, as the browser
                dst["n"][pos : pos + b] = np.sum(~np.isnan(sub), axis=1)
    tl = reader.timeline()
    return {
        "units": "celsius" if fmt is not None else "counts",
        "t_s": [tl["t_s"][int(i)] for i in keep],
        "frame_id": [tl["frame_id"][int(i)] for i in keep],
        "series": {str(rid): {k: _clean(v) for k, v in d.items()} for rid, d in acc.items()},
    }


__all__ = ["MAX_ROIS", "parse_rois", "roi_field", "roi_index", "roi_series"]
