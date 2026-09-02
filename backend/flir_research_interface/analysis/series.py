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
        else:
            raise ValueError(f"unknown roi kind {kind!r}")
    return out


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
            x0, y0 = max(0, r["x0"]), max(0, r["y0"])
            x1, y1 = min(w, r["x1"]), min(h, r["y1"])
            if x1 <= x0 or y1 <= y0:
                continue
            sub = field[:, y0:y1, x0:x1].reshape(stop - start, -1)
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


__all__ = ["MAX_ROIS", "parse_rois", "roi_series"]
