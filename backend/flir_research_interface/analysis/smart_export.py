"""Smart ROI columns for the ROI-series CSV and run-summary plot, read from the stored series.

The stored per-frame series (``smart_series``) is the single source: rows are by frame index, the
same order as ``roi_series``. Frames the tracker was ``searching`` (and any value that is NaN on
disk) are blank, never 0. A ROI without a usable stored series (not computed, or the frame count
changed) gets all-blank columns and a header comment saying so, so absence never reads as data.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from flir_research_interface.analysis.smart_series import (
    STATE_CODES,
    STATE_NAMES,
    load_smart_series,
)
from flir_research_interface.playback.reader import ExperimentReader

_DIM_COLUMNS: tuple[tuple[str, str], ...] = (
    ("area_px", "area px"),
    ("length_px", "length px"),
    ("width_px", "width px"),
    ("perimeter_px", "perimeter px"),
    ("centroid_x", "centroid x px"),
    ("centroid_y", "centroid y px"),
    ("sharpness_c_per_px", "sharpness C/px"),
    ("area_change_pct", "area change %"),
)
_DEFAULT_RINGS = (5, 10, 25)


def split_smart(rois: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(geometric ROIs, smart ROIs) preserving order."""
    return (
        [r for r in rois if r.get("kind") != "smart"],
        [r for r in rois if r.get("kind") == "smart"],
    )


def smart_label(roi: dict[str, Any]) -> str:
    return str(roi.get("name") or f"smart {roi['id']}")


def edge_note(roi: dict[str, Any]) -> str:
    """The thermal-edge rule in words, for the CSV header comment."""
    label = smart_label(roi)
    if roi.get("rule") == "fixed":
        rule = f"rule=fixed, fixed={float(roi.get('fixed_c') or 0.0):g} C"
    else:
        rule = f"rule=relative, sensitivity={float(roi.get('sensitivity', 0.5)):g}"
    return f"smart ROI {label}: thermal edge ({rule}); dimensions in pixels"


def _series_for(reader: ExperimentReader, roi: dict[str, Any]) -> dict[str, Any] | None:
    data = load_smart_series(reader.path, int(roi["id"]))
    if data is None or len(data["state"]) != reader.n_frames:
        return None
    return data


def _cell(v: float, searching: bool) -> str:
    return "" if searching or not math.isfinite(v) else f"{v:.4f}"


def smart_csv_block(
    reader: ExperimentReader, roi: dict[str, Any]
) -> tuple[str, list[str], list[list[str]]]:
    """``(header comment, column names, columns of n cell strings)`` for one smart ROI."""
    label = smart_label(roi)
    n = reader.n_frames
    data = _series_for(reader, roi)
    rings = [int(x) for x in (roi.get("rings_px") or _DEFAULT_RINGS)]
    inner = [0, *rings[:-1]]
    names = [f"{label} {s}" for s in ("mean", "max", "min", "state")]
    for a, b in zip(inner, rings, strict=True):
        names += [f"{label} ring {a}-{b} px {s}" for s in ("mean", "max", "min")]
    names += [f"{label} {title}" for _, title in _DIM_COLUMNS]
    note = edge_note(roi)
    if data is None:
        note += " [no stored series for this run: compute it, columns are blank]"
        return note, names, [[""] * n for _ in names]
    searching = np.asarray(data["state"]) == STATE_CODES["searching"]
    flags = [bool(x) for x in searching]
    cols: list[list[str]] = [
        [_cell(float(v), f) for v, f in zip(data[f"sample_{s}"], flags, strict=True)]
        for s in ("mean", "max", "min")
    ]
    cols.append([STATE_NAMES[int(c)] for c in data["state"]])
    for q in range(len(rings)):
        for s in ("mean", "max", "min"):
            ring = data[f"ring_{s}"]
            cols.append([
                _cell(float(ring[i, q]) if ring.ndim == 2 and q < ring.shape[1] else math.nan, f)
                for i, f in enumerate(flags)
            ])
    for key, _ in _DIM_COLUMNS:
        cols.append([_cell(float(v), f) for v, f in zip(data[key], flags, strict=True)])
    return note, names, cols


def smart_plot_trace(reader: ExperimentReader, roi: dict[str, Any]) -> np.ndarray | None:
    """Sample mean per frame (NaN while searching/unknown) for the run-summary plot, or None."""
    data = _series_for(reader, roi)
    if data is None:
        return None
    mean = np.asarray(data["sample_mean"], dtype=float).copy()
    mean[np.asarray(data["state"]) == STATE_CODES["searching"]] = np.nan
    return mean
