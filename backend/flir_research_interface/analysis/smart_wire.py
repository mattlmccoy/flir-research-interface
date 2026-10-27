"""Smart ROI wire format: the operator's per-frame outline sent to the browser.

Labels (0 none, 1 sample, 2.. rings) are run-length encoded row-major as packed
``(uint8 value, uint32 run)`` little-endian pairs (5 bytes each), then base64.
"""

from __future__ import annotations

import base64
from typing import Any

import numpy as np
import numpy.typing as npt

from .smart_roi import SmartResult

_PAIR = np.dtype([("value", "u1"), ("run", "<u4")])


def encode_labels(labels: npt.NDArray[np.uint8]) -> str:
    """Run-length encode a uint8 label crop (row-major) to a base64 string."""
    flat = np.ascontiguousarray(labels, dtype=np.uint8).ravel()
    if flat.size == 0:
        return ""
    starts = np.concatenate(([0], np.flatnonzero(np.diff(flat)) + 1))
    pairs = np.empty(starts.size, dtype=_PAIR)
    pairs["value"] = flat[starts]
    pairs["run"] = np.diff(np.concatenate((starts, [flat.size])))
    return base64.b64encode(pairs.tobytes()).decode("ascii")


def smart_overlay(result: SmartResult, roi_id: int) -> dict[str, Any]:
    """The per-frame overlay payload for one smart ROI (``labels`` None when not located).

    ``over`` is present only while the sample or a ring has over-range pixels: the bounded
    readings for the browser (``{"sample": stats, "rings": [stats, ...]}``, each stats
    ``{mean_lb_c, min_c, min_is_bound, max_c, over_px, ceiling_c}``). It is a display channel only:
    the control feed (``live_temps``) keeps such an ROI ``valid=False`` with null temperatures."""
    out: dict[str, Any] = {
        "id": roi_id,
        "state": result.state,
        "valid": result.valid,
        "bbox": list(result.bbox) if result.bbox is not None else None,
        "labels": encode_labels(result.labels) if result.labels is not None else None,
    }
    if result.over_stats is not None:
        out["over"] = {
            "sample": dict(result.over_stats["sample"]),
            "rings": [dict(g) for g in result.over_stats["rings"]],
        }
    return out
