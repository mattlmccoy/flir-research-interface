"""Smart ROI over a recorded run: the full-rate tracker job and its per-frame store.

``compute_smart_series`` steps ONE ``SmartTracker`` over every frame INDEX of a recording in
order (stride 1; time from ``reader.t_s(i)``), with the run's camera constants and the ROI's own
optics so ``ring_emissivity`` applies. Results are keyed by frame index, never by frame id (A70
ids are 16-bit and wrap/reset). Playback (plot + overlay) and exports read the same stored rows,
so they agree frame for frame.

Store, under ``<run>/smart_roi/``:

* ``<id>.npz`` (no pickled objects): ``t_s`` (n), ``state`` (uint8, see ``STATE_CODES``),
  ``valid`` / ``over_range`` (bool), ``edge_level_c``, ``sample_mean|max|min`` (n),
  ``ring_mean|max|min`` (n x k), one float column per numeric ``dims`` key (``DIM_KEYS``),
  ``bbox`` (n x 4 int32, -1 when not located) and the encoded label crops as
  ``labels_blob`` (ASCII bytes) + ``labels_off`` (n+1 offsets; an empty slice = not located).
* over-range readings (``smart_roi._over_stats``; NaN / 0 on rows with no over-range pixel there):
  ``sample_mean_lb`` / ``sample_min_over`` (n), ``sample_min_is_bound`` (bool), ``over_px``
  (int32), the ring equivalents ``ring_mean_lb`` / ``ring_min_over`` / ``ring_min_is_bound`` /
  ``ring_over_px`` (n x k), and ``ceiling_c`` = [sample, ring] range top in each field (NaN
  unknown). Series computed before these columns existed have none of them.
* ``<id>.spec.json``: the spec, optics and frame count the series was computed from.

Missing values are NaN on disk; ``load_smart_series`` returns ``labels`` decoded to an object
array of strings / ``None``.
"""

from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from flir_research_interface.analysis.smart_roi import SmartRoiSpec, SmartTracker
from flir_research_interface.analysis.smart_wire import encode_labels
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.radiometry.overrange import over_range_mask
from flir_research_interface.radiometry.temperature_linear import (
    IRFormat,
    counts_to_celsius,
    kelvin_per_count,
)

logger = logging.getLogger(__name__)

SMART_DIR = "smart_roi"
STATE_CODES: dict[str, int] = {"searching": 0, "locked": 1, "holding": 2}
STATE_NAMES: tuple[str, ...] = ("searching", "locked", "holding")
DIM_KEYS: tuple[str, ...] = (
    "area_px", "length_px", "width_px", "perimeter_px", "centroid_x", "centroid_y",
    "sharpness_c_per_px", "area_change_pct", "length_change_pct", "width_change_pct",
)
_BATCH = 32  # frames read from the store at once
_OPTIC_KEYS = ("emissivity", "reflected_c")


def series_path(run_dir: Path, roi_id: int) -> Path:
    return Path(run_dir) / SMART_DIR / f"{int(roi_id)}.npz"


def _spec_path(run_dir: Path, roi_id: int) -> Path:
    return Path(run_dir) / SMART_DIR / f"{int(roi_id)}.spec.json"


def _f(v: Any) -> float:
    return float(v) if v is not None else math.nan


def stored_optics(reader: ExperimentReader, roi_id: int) -> dict[str, Any]:
    """The emissivity / reflected temperature stored with the run's ROI ``roi_id`` (if any)."""
    for r in reader.metadata.get("rois") or []:
        if isinstance(r, dict) and r.get("id") == roi_id:
            return {k: r[k] for k in _OPTIC_KEYS if r.get(k) is not None}
    return {}


def smart_series_stale(reader: ExperimentReader, spec: SmartRoiSpec, data: dict[str, Any]) -> bool:
    """True when the stored series was computed from a different ROI spec / optics / frame count
    than ``spec`` and the run's stored optics (the ROI was edited after the series was computed)."""
    now = {**asdict(spec), "search": [list(p) for p in spec.search],
           "rings_px": list(spec.rings_px)}
    then = dict(data.get("spec") or {})
    now.pop("name", None)  # a rename does not change the tracking
    then.pop("name", None)
    return (
        now != then
        or stored_optics(reader, spec.id) != data.get("optics")
        or reader.n_frames != len(data["state"])
    )


def run_ceiling(camera: dict[str, Any] | None) -> float | None:
    """The top of the run's active measurement case (°C), or None when not recorded."""
    case = (camera or {}).get("active_case")
    v = case.get("high_c") if isinstance(case, dict) else None
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def compute_smart_series(
    reader: ExperimentReader,
    spec: SmartRoiSpec,
    on_progress: Callable[[int, int], None] | None = None,
    *,
    optics: dict[str, Any] | None = None,
    out_dir: Path | None = None,
) -> Path:
    """Track ``spec`` over every frame of ``reader`` and write ``<run>/smart_roi/<id>.npz``.

    ``optics`` defaults to the ROI's stored emissivity / reflected temperature. Raises
    ``ValueError`` when the recording is not temperature-linear (nothing to track in °C).
    ``out_dir`` (default: the run folder) is the directory that gets the ``smart_roi/`` store."""
    try:
        fmt = IRFormat(reader.ir_format or "")
    except ValueError as exc:
        raise ValueError(f"recording is not temperature-linear ({reader.ir_format!r})") from exc
    if fmt is IRFormat.RADIOMETRIC:
        raise ValueError("recording is not temperature-linear (Radiometric)")
    kpc = kelvin_per_count(fmt)
    if optics is None:
        optics = stored_optics(reader, spec.id)
    n, k = reader.n_frames, len(spec.rings_px)
    _, h, w = reader.counts_block(0, 1).shape if n else (0, 0, 0)
    tracker = SmartTracker(spec, w, h, cam=reader.metadata.get("camera"), optics=optics)
    ceiling = run_ceiling(reader.metadata.get("camera"))

    cols: dict[str, np.ndarray] = {
        "t_s": np.array([reader.t_s(i) for i in range(n)], dtype=np.float64),
        "state": np.zeros(n, dtype=np.uint8),
        "valid": np.zeros(n, dtype=bool),
        "over_range": np.zeros(n, dtype=bool),
        "edge_level_c": np.full(n, np.nan),
        "bbox": np.full((n, 4), -1, dtype=np.int32),
    }
    for s in ("mean", "max", "min"):
        cols[f"sample_{s}"] = np.full(n, np.nan)
        cols[f"ring_{s}"] = np.full((n, k), np.nan)
    for key in DIM_KEYS:
        cols[key] = np.full(n, np.nan)
    for where, shape in (("sample", (n,)), ("ring", (n, k))):
        cols[f"{where}_mean_lb"] = np.full(shape, np.nan)
        cols[f"{where}_min_over"] = np.full(shape, np.nan)
        cols[f"{where}_min_is_bound"] = np.zeros(shape, dtype=bool)
    cols["over_px"] = np.zeros(n, dtype=np.int32)
    cols["ring_over_px"] = np.zeros((n, k), dtype=np.int32)
    cols["ceiling_c"] = np.array([_f(c) for c in tracker.field_ceilings(ceiling)])
    labels: list[bytes] = []

    for start in range(0, n, _BATCH):
        block = reader.counts_block(start, min(n, start + _BATCH))
        for j, counts in enumerate(block):
            i = start + j
            r = tracker.update(counts_to_celsius(counts, fmt), float(cols["t_s"][i]),
                               over_range_mask(counts, kelvin_per_count=kpc), ceiling_c=ceiling)
            cols["state"][i] = STATE_CODES[r.state]
            cols["valid"][i] = r.valid
            cols["over_range"][i] = r.over_range
            cols["edge_level_c"][i] = _f(r.edge_level_c)
            if r.bbox is not None:
                cols["bbox"][i] = r.bbox
            for s in ("mean", "max", "min"):
                cols[f"sample_{s}"][i] = _f(r.sample.get(f"{s}_c"))
                for q, ring in enumerate(r.rings[:k]):
                    cols[f"ring_{s}"][i, q] = _f(ring.get(f"{s}_c"))
            if r.dims is not None:
                for key in DIM_KEYS:
                    cols[key][i] = _f(r.dims.get(key))
            if r.over_stats is not None:
                _store_over(cols, i, r.over_stats, k)
            labels.append(encode_labels(r.labels).encode("ascii") if r.labels is not None else b"")
        if on_progress is not None:
            on_progress(min(n, start + _BATCH), n)
    if on_progress is not None and n == 0:
        on_progress(0, 0)

    sizes = np.array([len(b) for b in labels], dtype=np.int64)
    cols["labels_off"] = np.concatenate(([0], np.cumsum(sizes))).astype(np.int64)
    cols["labels_blob"] = np.frombuffer(b"".join(labels), dtype=np.uint8)
    return _write(out_dir if out_dir is not None else reader.path, spec, optics, n, cols)


def _store_over(cols: dict[str, np.ndarray], i: int, over: dict[str, Any], k: int) -> None:
    """Row ``i`` of the over-range columns; only regions that have over-range pixels are filled."""
    cells: list[tuple[str, dict[str, Any], tuple[int, ...], str]] = [
        ("sample", over["sample"], (i,), "over_px")
    ]
    cells += [("ring", g, (i, q), "ring_over_px") for q, g in enumerate(over["rings"][:k])]
    for where, st, at, px in cells:
        if not st["over_px"]:
            continue
        cols[px][at] = st["over_px"]
        cols[f"{where}_mean_lb"][at] = _f(st["mean_lb_c"])
        cols[f"{where}_min_over"][at] = _f(st["min_c"])
        cols[f"{where}_min_is_bound"][at] = st["min_is_bound"]


def _write(
    run_dir: Path, spec: SmartRoiSpec, optics: dict[str, Any], n: int, cols: dict[str, np.ndarray]
) -> Path:
    """Write the npz and its spec sidecar atomically (temp file + rename)."""
    out = series_path(run_dir, spec.id)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    with tmp.open("wb") as fh:
        np.savez_compressed(fh, allow_pickle=False, **cols)
    os.replace(tmp, out)
    side = {
        "spec": {**asdict(spec), "search": [list(p) for p in spec.search],
                 "rings_px": list(spec.rings_px)},
        "optics": optics,
        "n_frames": n,
        "computed_utc": datetime.now(UTC).isoformat(),
    }
    sp = _spec_path(run_dir, spec.id)
    tmp_s = sp.with_name(sp.name + ".tmp")
    tmp_s.write_text(json.dumps(side, indent=2))
    os.replace(tmp_s, sp)
    logger.info("smart ROI %d: %d frames -> %s", spec.id, n, out)
    return out


def load_smart_series(run_dir: Path, roi_id: int) -> dict[str, Any] | None:
    """The stored series for ``roi_id`` (arrays as written, ``labels`` decoded, plus ``spec``,
    ``optics``, ``n_frames``, ``computed_utc`` and ``rings_px`` from the sidecar), or ``None`` if
    not computed."""
    path = series_path(run_dir, roi_id)
    if not path.is_file():
        return None
    with np.load(path, allow_pickle=False) as z:
        out: dict[str, Any] = {name: z[name] for name in z.files}
    blob, off = out.pop("labels_blob").tobytes(), out.pop("labels_off")
    labels = np.empty(len(off) - 1, dtype=object)
    for i in range(len(labels)):
        a, b = int(off[i]), int(off[i + 1])
        labels[i] = blob[a:b].decode("ascii") if b > a else None
    out["labels"] = labels
    sp = _spec_path(run_dir, roi_id)
    side: dict[str, Any] = json.loads(sp.read_text()) if sp.is_file() else {}
    out["spec"] = side.get("spec")
    out["optics"] = side.get("optics", {})
    out["n_frames"] = side.get("n_frames", len(labels))
    out["computed_utc"] = side.get("computed_utc")
    out["rings_px"] = list((side.get("spec") or {}).get("rings_px") or [])
    return out


def _clean(a: np.ndarray) -> list[float | None]:
    return [float(v) if math.isfinite(float(v)) else None for v in a]


def series_payload(data: dict[str, Any], max_points: int) -> dict[str, Any]:
    """The plot payload: every ``stride``-th stored row so at most ``max_points`` remain.
    Missing values are ``None`` (gaps); ``index`` gives each point's frame index;
    ``computed_utc`` says which compute produced it (None for a series without a sidecar)."""
    n = len(data["state"])
    stride = max(1, math.ceil(n / max(1, max_points)))
    idx = np.arange(0, n, stride)
    rings_px = data.get("rings_px") or []
    k = data["ring_mean"].shape[1] if data["ring_mean"].ndim == 2 else 0
    inners = [0, *rings_px][:k]
    rings = [
        {
            "inner_px": int(inners[q]) if q < len(inners) else None,
            "outer_px": int(rings_px[q]) if q < len(rings_px) else None,
            **{s: _clean(data[f"ring_{s}"][idx, q]) for s in ("mean", "max", "min")},
        }
        for q in range(k)
    ]
    dims: dict[str, Any] = {key: _clean(data[key][idx]) for key in DIM_KEYS}
    dims["units"] = "px"
    over_range = data.get("over_range")
    return {
        "index": [int(i) for i in idx],
        "t_s": [float(t) for t in data["t_s"][idx]],
        "state": [STATE_NAMES[int(c)] for c in data["state"][idx]],
        "valid": [bool(v) for v in data["valid"][idx]],
        "sample": {s: _clean(data[f"sample_{s}"][idx]) for s in ("mean", "max", "min")},
        "rings": rings,
        "dims": dims,
        "computed_utc": data.get("computed_utc"),
        # rows where the sample had over-range pixels (every stored series has this column)
        "over_range": [bool(v) for v in over_range[idx]] if over_range is not None else None,
        "over": _over_payload(data, idx, k),
    }


def _over_payload(data: dict[str, Any], idx: np.ndarray, k: int) -> dict[str, Any] | None:
    """The bounded over-range readings at rows ``idx``, or None for a series computed before they
    were stored (recompute to add them)."""
    if "over_px" not in data or "ceiling_c" not in data:
        return None

    def block(where: str, px: np.ndarray, q: int | None) -> dict[str, Any]:
        cut = (idx,) if q is None else (idx, q)
        return {
            "mean_lb": _clean(data[f"{where}_mean_lb"][cut]),
            "min": _clean(data[f"{where}_min_over"][cut]),
            "min_is_bound": [bool(v) for v in data[f"{where}_min_is_bound"][cut]],
            "px": [int(v) for v in px[cut]],
        }

    ceil = _clean(np.asarray(data["ceiling_c"], dtype=np.float64))
    return {
        "ceiling_c": ceil[0] if ceil else None,
        "ring_ceiling_c": ceil[1] if len(ceil) > 1 else None,
        "sample": block("sample", data["over_px"], None),
        "rings": [block("ring", data["ring_over_px"], q) for q in range(k)],
    }


def overlay_window(
    data: dict[str, Any], roi_id: int, start: int, count: int
) -> list[dict[str, Any]]:
    """Stored per-frame overlays (``smart_overlay`` shape) for frame indices
    ``[start, start + count)``, clipped to the run."""
    n = len(data["state"])
    out: list[dict[str, Any]] = []
    for i in range(max(0, start), min(n, start + count)):
        box = [int(v) for v in data["bbox"][i]]
        row: dict[str, Any] = {
            "id": roi_id,
            "state": STATE_NAMES[int(data["state"][i])],
            "valid": bool(data["valid"][i]),
            "bbox": box if box[0] >= 0 else None,
            "labels": data["labels"][i],
        }
        over = _stored_over(data, i)
        if over is not None:
            row["over"] = over
        out.append(row)
    return out


def _stored_over(data: dict[str, Any], i: int) -> dict[str, Any] | None:
    """Row ``i``'s ``over`` block in the live overlay's shape (``smart_wire.smart_overlay``), or
    None when nothing there was over range or the series predates the over-range columns. A region
    without over-range pixels gets its plain stored numbers."""
    if "over_px" not in data or "ceiling_c" not in data:
        return None
    ring_px = data["ring_over_px"][i]
    if int(data["over_px"][i]) == 0 and not bool(np.any(ring_px)):
        return None
    ceil = _clean(np.asarray(data["ceiling_c"], dtype=np.float64))

    def one(where: str, at: tuple[int, ...], px: int, ceiling: float | None) -> dict[str, Any]:
        def v(col: str) -> float | None:
            return _clean(np.asarray([data[col][at]], dtype=np.float64))[0]

        if px:
            return {"mean_lb_c": v(f"{where}_mean_lb"), "min_c": v(f"{where}_min_over"),
                    "min_is_bound": bool(data[f"{where}_min_is_bound"][at]), "max_c": None,
                    "over_px": px, "ceiling_c": ceiling}
        return {"mean_lb_c": v(f"{where}_mean"), "min_c": v(f"{where}_min"),
                "min_is_bound": False, "max_c": v(f"{where}_max"), "over_px": 0,
                "ceiling_c": ceiling}

    return {
        "sample": one("sample", (i,), int(data["over_px"][i]), ceil[0] if ceil else None),
        "rings": [one("ring", (i, q), int(px), ceil[1] if len(ceil) > 1 else None)
                  for q, px in enumerate(ring_px)],
    }


__all__ = [
    "DIM_KEYS",
    "SMART_DIR",
    "STATE_CODES",
    "STATE_NAMES",
    "compute_smart_series",
    "load_smart_series",
    "overlay_window",
    "run_ceiling",
    "series_payload",
    "series_path",
    "smart_series_stale",
    "stored_optics",
]
