"""Exports (Milestone 7): ROI series CSV, single frames (CSV/TIFF/PNG/NPY), whole runs (HDF5).

Every export is derived from the read-only ``ExperimentReader``; the canonical Zarr store is
never modified. HDF5 files land in ``<experiment>/exports/`` next to the store so "reveal"
finds them. Temperatures use the recording's own conversion rule (``metadata.json``); raw
count exports stay uint16 so nothing is lost.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import zipfile
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import numpy.typing as npt
from PIL import Image

from flir_research_interface import __version__
from flir_research_interface.analysis.series import roi_series
from flir_research_interface.analysis.smart_export import smart_csv_block, split_smart
from flir_research_interface.labels import export_label, read_labels
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.radiometry.temperature_linear import (
    KELVIN_OFFSET,
    IRFormat,
    counts_to_celsius,
    kelvin_per_count,
)

FRAME_FORMATS: dict[str, tuple[str, str]] = {
    "csv": ("text/csv", ".csv"),
    "tiff": ("image/tiff", ".tiff"),
    "png": ("image/png", ".png"),
    "npy": ("application/octet-stream", ".npy"),
}
CONVERSION_RULE = "celsius = counts * kelvin_per_count - kelvin_offset"


def _linear_format(reader: ExperimentReader) -> IRFormat | None:
    try:
        fmt = IRFormat(reader.ir_format or "")
    except ValueError:
        return None
    return None if fmt is IRFormat.RADIOMETRIC else fmt


def _roi_desc(r: dict[str, Any]) -> str:
    return _roi_geom(r) + _roi_optics(r)


def _roi_optics(r: dict[str, Any]) -> str:
    parts = []
    if "emissivity" in r:
        parts.append(f"emissivity={r['emissivity']:g}")
    if "reflected_c" in r:
        parts.append(f"reflected_c={r['reflected_c']:g}")
    if "distance_m" in r:
        parts.append(f"distance_m={r['distance_m']:g}")
    return f" [{', '.join(parts)}]" if parts else ""


def _roi_geom(r: dict[str, Any]) -> str:
    k = r["kind"]
    if k == "smart":
        rings = r.get("rings_px") or [5, 10, 25]
        return (
            f"M{r['id']}: smart ROI search={r.get('search')} rings_px={rings} "
            f"rule={r.get('rule', 'relative')} (tracked outline per frame)"
        )
    if k == "spot":
        box = " (mean of 3x3)" if r.get("box") == 3 else ""
        return f"S{r['id']}: spot x={r['x']} y={r['y']}{box}"
    if k == "rect":
        return f"R{r['id']}: rect x0={r['x0']} y0={r['y0']} x1={r['x1']} y1={r['y1']} (half-open)"
    if k == "polyline":
        return f"B{r['id']}: polyline points={r['points']} (Bresenham per segment)"
    if k == "ellipse":
        return f"E{r['id']}: ellipse cx={r['cx']} cy={r['cy']} rx={r['rx']} ry={r['ry']}"
    if k == "circle":
        return f"C{r['id']}: circle cx={r['cx']} cy={r['cy']} r={r['r']} (pixel centres within r)"
    if k == "line":
        seg = f"x0={r['x0']} y0={r['y0']} x1={r['x1']} y1={r['y1']}"
        return f"L{r['id']}: line {seg} (Bresenham, inclusive)"
    return f"P{r['id']}: polygon points={r['points']} (even-odd interior + boundary)"


def series_csv(reader: ExperimentReader, rois: list[dict[str, Any]]) -> str:
    """ROI values on every frame as CSV with ``#`` header comments documenting units and ROIs."""
    geo, smart = split_smart(rois)
    data = roi_series(reader, geo)
    buf = io.StringIO()
    buf.write(f"# FLIR Research Interface {__version__} ROI series\n")
    buf.write(f"# experiment: {reader.path.name}\n")
    buf.write(f"# units: {data['units']}\n")
    buf.write("# t_s: seconds since the first recorded frame (camera clock)\n")
    for r in geo:
        buf.write(f"# {_roi_desc(r)}\n")
    blocks = [smart_csv_block(reader, r) for r in smart]
    for note, _names, _cells in blocks:
        buf.write(f"# {note}\n")
    header = ["t_s", "frame_id"]
    cols: list[list[float | None]] = []
    for r in geo:
        s = data["series"][str(r["id"])]
        prefix = {"spot": "S", "rect": "R", "circle": "C", "line": "L", "polygon": "P"}[r["kind"]]
        if r["kind"] == "spot":
            header.append(f"S{r['id']}_value")
            cols.append(s["value"])
        else:
            for k in ("mean", "min", "max", "std", "n"):
                header.append(f"{prefix}{r['id']}_{k}")
                cols.append(s[k])
    for _note, names, _cells in blocks:
        header += names
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for i, (t, fid) in enumerate(zip(data["t_s"], data["frame_id"], strict=True)):
        row = [f"{t:.6f}", fid] + ["" if c[i] is None else f"{c[i]:.4f}" for c in cols]
        for _note, _names, cells in blocks:
            row += [c[i] for c in cells]
        w.writerow(row)
    return buf.getvalue()


def frame_bytes(reader: ExperimentReader, index: int, fmt: str) -> tuple[bytes, str, str]:
    """One frame as ``(bytes, media_type, filename)``.

    csv/tiff carry °C (float) when the recording is temperature-linear, else raw counts;
    png/npy always carry the raw uint16 counts.
    """
    if fmt not in FRAME_FORMATS:
        raise ValueError(f"unknown export format {fmt!r}; choose one of {sorted(FRAME_FORMATS)}")
    frame = reader.frame(index)
    media, ext = FRAME_FORMATS[fmt]
    filename = f"{export_label(reader.path)}_frame{index:04d}{ext}"
    linear = _linear_format(reader)
    celsius: npt.NDArray[np.float32] | None = (
        counts_to_celsius(frame.counts, linear) if linear is not None else None
    )
    if fmt == "csv":
        text = io.StringIO()
        units = "celsius" if celsius is not None else "counts"
        text.write(f"# experiment: {reader.path.name}  frame_index: {index}\n")
        text.write(f"# frame_id: {frame.frame_id}  t_s: {reader.t_s(index):.6f}  units: {units}\n")
        text.write("# rows = image rows (y, top first); columns = x\n")
        grid: npt.NDArray[Any] = celsius if celsius is not None else frame.counts
        np.savetxt(text, grid, fmt="%.3f" if celsius is not None else "%d", delimiter=",")
        return text.getvalue().encode("utf-8"), media, filename
    out = io.BytesIO()
    if fmt == "tiff":
        img = (
            Image.fromarray(np.ascontiguousarray(celsius, dtype=np.float32), mode="F")
            if celsius is not None
            else Image.fromarray(np.ascontiguousarray(frame.counts, dtype=np.uint16))
        )
        img.save(out, format="TIFF")
    elif fmt == "png":
        Image.fromarray(np.ascontiguousarray(frame.counts, dtype=np.uint16)).save(out, format="PNG")
    else:
        np.save(out, np.ascontiguousarray(frame.counts, dtype=np.uint16))
    return out.getvalue(), media, filename


RANGE_FORMATS = ("csv", "tiff", "png", "npy", "tiff-stack")


def export_frame_range(
    reader: ExperimentReader, start: int, stop: int, step: int, fmt: str
) -> dict[str, Any]:
    """Frames ``range(start, stop, step)`` as a zip of per-frame files (csv/tiff/png/npy) or a
    multi-page float TIFF stack (``tiff-stack``), written under ``exports/``."""
    if fmt not in RANGE_FORMATS:
        raise ValueError(f"unknown format {fmt!r}; choose one of {RANGE_FORMATS}")
    if step < 1 or start < 0 or stop > reader.n_frames or start >= stop:
        raise ValueError("need 0 <= start < stop <= n_frames and step >= 1")
    indices = list(range(start, stop, step))
    out_dir = reader.path / "exports"
    out_dir.mkdir(exist_ok=True)
    tag = f"{export_label(reader.path)}_frames_{start:04d}-{indices[-1]:04d}_step{step}"
    if fmt == "tiff-stack":
        linear = _linear_format(reader)
        pages = []
        for i in indices:
            fr = reader.frame(i)
            arr = counts_to_celsius(fr.counts, linear) if linear is not None else fr.counts
            pages.append(
                Image.fromarray(np.ascontiguousarray(arr, dtype=np.float32), mode="F")
                if linear is not None
                else Image.fromarray(np.ascontiguousarray(arr, dtype=np.uint16))
            )
        path = out_dir / f"{tag}.tif"
        pages[0].save(path, format="TIFF", save_all=True, append_images=pages[1:])
    else:
        path = out_dir / f"{tag}_{fmt}.zip"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for i in indices:
                data, _media, _name = frame_bytes(reader, i, fmt)
                z.writestr(f"frame_{i:04d}{FRAME_FORMATS[fmt][1]}", data)
    return {
        "path": str(path),
        "frames": indices,
        "n": len(indices),
        "format": fmt,
        "size_bytes": path.stat().st_size,
    }


def _remove_superseded_hdf5(keep: Path, experiment: str) -> None:
    """Delete earlier HDF5 exports of the same run (``attrs["experiment"]`` matches) left under a
    previous name. Files that are unreadable or from another run are never touched."""
    for other in keep.parent.glob("*.h5"):
        if other == keep:
            continue
        try:
            with h5py.File(other, "r") as f:
                same = f.attrs.get("experiment") == experiment
        except (OSError, ValueError):
            continue
        if same:
            other.unlink(missing_ok=True)


def export_hdf5(reader: ExperimentReader, *, batch: int = 64) -> dict[str, Any]:
    """Write ``<experiment>/exports/<label>.h5`` (gzip'd uint16 counts + time axes + metadata).

    ``<label>`` carries the run's display name (see ``labels.export_label``). After a rename, the
    previous HDF5 export of this same run (identified by its ``experiment`` attribute) is removed
    once the new one is complete, so a multi-GB duplicate is not left behind."""
    out_dir = reader.path / "exports"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{export_label(reader.path)}.h5"
    tmp = out.with_name(out.name + ".tmp")
    info = reader.info()
    n, h, w = reader.n_frames, int(info["height"]), int(info["width"])
    linear = _linear_format(reader)
    with h5py.File(tmp, "w") as f:
        ds = f.create_dataset(
            "counts",
            shape=(n, h, w),
            dtype="uint16",
            chunks=(max(1, min(32, n)), h, w),
            compression="gzip",
            compression_opts=4,
        )
        ds.attrs["description"] = "raw camera counts, row-major (frame, y, x)"
        for start in range(0, n, max(1, batch)):
            stop = min(n, start + batch)
            ds[start:stop] = reader.counts_block(start, stop)
        tl = reader.timeline()
        f.create_dataset("t_s", data=np.asarray(tl["t_s"], dtype=np.float64))
        f.create_dataset("frame_id", data=np.asarray(tl["frame_id"], dtype=np.int64))
        dev, host = reader.timestamps_ns()
        f.create_dataset("device_timestamp_ns", data=dev)
        f.create_dataset("host_timestamp_ns", data=host)
        f.attrs["experiment"] = reader.path.name
        f.attrs["title"] = read_labels(reader.path).get("title") or ""
        f.attrs["software"] = f"FLIR Research Interface {__version__}"
        f.attrs["ir_format"] = reader.ir_format or ""
        f.attrs["pixel_format"] = reader.pixel_format
        if linear is not None:
            f.attrs["kelvin_per_count"] = kelvin_per_count(linear)
            f.attrs["kelvin_offset"] = KELVIN_OFFSET
            f.attrs["conversion"] = CONVERSION_RULE
        else:
            f.attrs["conversion"] = "counts are not temperature-linear; no conversion rule"
        f.attrs["metadata_json"] = json.dumps(reader.metadata)
        f.attrs["events_json"] = json.dumps(reader.events)
    os.replace(tmp, out)
    _remove_superseded_hdf5(out, reader.path.name)
    data = out.read_bytes()
    return {
        "path": str(out),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "n_frames": n,
    }


__all__ = ["FRAME_FORMATS", "export_hdf5", "frame_bytes", "series_csv"]
