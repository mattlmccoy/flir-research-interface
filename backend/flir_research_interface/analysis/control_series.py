"""Read a run's control/telemetry trace (the CXN loop's samples) into plottable series on the
run's relative time axis, so RF power etc. can be overlaid on the ROI-temperature plot.

Each control sample was stamped with the ``frame_id`` it landed on; we map that to the frame's
relative time ``t_s`` from the recording's timeline, so the trace lines up with the temperature
readings exactly (the alignment Matt asked for). Samples without a usable frame_id are dropped.

The source of truth is the run's ``events.json`` (type ``control``) — those are always frame-stamped
by the recorder — with a CSV parser kept for the exports/control.csv form.
"""

from __future__ import annotations

import csv
import io
from typing import Any

# Numeric columns worth plotting (in a sensible default order). ts / t_utc / frame_id are the
# alignment keys; roi/phase/mode are labels, not series.
NUMERIC_COLUMNS = (
    "forward_w", "reverse_w", "reflected_fraction", "setpoint_c", "measured_c",
    "applied_w", "recommended_w", "error_c",
)


def _num(cell: Any) -> float | None:
    """A plottable float, or None for blank/missing/non-numeric (plots as a gap, not a zero)."""
    if cell is None or cell == "":
        return None
    try:
        return float(cell)
    except (TypeError, ValueError):
        return None


def control_series_from_rows(
    rows: list[dict[str, Any]], frame_t_s: dict[int, float]
) -> dict[str, Any]:
    """``{"t_s": [...], "<col>": [...], ...}`` from control samples (dict rows) on the run timeline.

    ``frame_t_s`` maps frame_id → relative seconds. Rows whose frame_id is missing/blank or not in
    the timeline are skipped. Only ``NUMERIC_COLUMNS`` present in at least one row are returned,
    each parallel to ``t_s``.
    """
    present = [c for c in NUMERIC_COLUMNS if any(c in r for r in rows)]
    out: dict[str, list[Any]] = {"t_s": []}
    for c in present:
        out[c] = []
    for row in rows:
        fid_raw = row.get("frame_id")
        if fid_raw is None or fid_raw == "":
            continue
        try:
            fid = int(fid_raw)
        except (TypeError, ValueError):
            continue
        if fid not in frame_t_s:
            continue
        out["t_s"].append(frame_t_s[fid])
        for c in present:
            out[c].append(_num(row.get(c)))
    return out


def parse_control_csv(text: str, frame_t_s: dict[int, float]) -> dict[str, Any]:
    """Parse an ``exports/control.csv`` (with a frame_id column) into the same series shape."""
    return control_series_from_rows(list(csv.DictReader(io.StringIO(text))), frame_t_s)


__all__ = ["control_series_from_rows", "parse_control_csv", "NUMERIC_COLUMNS"]
