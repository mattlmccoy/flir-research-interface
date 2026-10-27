"""Live per-ROI temperature payload for closed-loop control (GET /api/live/roi-temps).

A separate controller (the TC-POWER / CXN session) polls this each control tick and regulates RF
power to a temperature setpoint. The payload is therefore a *safety signal*: an absent, stale, or
over-range reading must be reported as ``valid=False`` with ``null`` temperatures so the controller
can hold power, never a plausible number it would act on. All temperature computation reuses the
same ROI indexing and over-range exclusion as the recorded-series path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import numpy as np

from flir_research_interface.analysis.series import roi_index
from flir_research_interface.analysis.smart_spec import parse_smart_roi
from flir_research_interface.radiometry.overrange import over_range_mask
from flir_research_interface.radiometry.temperature_linear import (
    IRFormat,
    counts_to_celsius,
    kelvin_per_count,
)

if TYPE_CHECKING:
    from flir_research_interface.analysis.smart_roi import SmartResult

STALE_MS = 1000.0  # a frame older than this (or no frame) is untrustworthy for control
# A smart ROI result must come from the reported frame. The tracker runs as a camera-thread listener
# *before* the frame is published, so a healthy result is stamped with the reported frame or a newer
# one; lagging means the tracker failed on the frames since. Allow ~1.5 frame periods at 30 fps of
# slack, then report the ROI invalid rather than an outline the controller cannot trust.
SMART_LAG_MS = 50.0


def _iso(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).isoformat()


def _null_rings(roi: dict[str, Any]) -> list[dict[str, Any]]:
    """One ring entry per ``rings_px`` offset with null stats (an invalid entry's rings). A ROI
    whose spec does not parse has no trustworthy ring list, so it gets none."""
    try:
        rings = parse_smart_roi(roi).rings_px
    except (ValueError, TypeError):
        return []
    return [
        {"inner_px": a, "outer_px": b, "mean_c": None, "max_c": None, "min_c": None}
        for a, b in zip((0, *rings), rings, strict=False)
    ]


def _invalid_roi(roi: dict[str, Any], *, over_range: bool = False) -> dict[str, Any]:
    """An ROI entry with no trustworthy temperature (names the ROI so the roster stays stable)."""
    out: dict[str, Any] = {
        "id": roi.get("id"), "name": roi.get("name"), "kind": roi.get("kind"),
        "mean_c": None, "max_c": None, "min_c": None, "value_c": None,
        "over_range": over_range, "valid": False,
    }
    if roi.get("kind") == "smart":  # keep the smart keys present so the shape never changes
        out.update({"state": "searching", "rings": _null_rings(roi), "dims": None})
    return out


def _smart_entry(
    roi: dict[str, Any], result: SmartResult | None, frame_ts_ns: int
) -> dict[str, Any]:
    """A smart ROI's feed entry: today's flat keys plus ``state``, ``rings`` and ``dims``
    (spec §7a). Valid only when the tracker says so *and* it measured a sample temperature —
    holding stays valid (spec §7b) until the tracker's hold window lapses."""
    if result is None:  # no tracker result yet (new ROI, bad spec, no frame tracked)
        return _invalid_roi(roi)
    stamp = result.frame_ts_ns
    if stamp is None or (frame_ts_ns - stamp) / 1e6 > SMART_LAG_MS:
        return _invalid_roi(roi)  # unknown or left behind by a failed frame: never healthy
    sample = result.sample or {}
    temps = {k: sample.get(k) for k in ("mean_c", "max_c", "min_c")}
    valid = bool(result.valid) and all(isinstance(v, float) for v in temps.values())
    if not valid:
        entry = _invalid_roi(roi, over_range=bool(result.over_range))
        entry["state"] = result.state  # rings stay null: an invalid entry never carries numbers
        return entry
    return {
        "id": roi.get("id"), "name": roi.get("name"), "kind": "smart",
        **temps,
        "value_c": None,
        "over_range": False,
        "valid": True,
        "state": result.state,
        "rings": [dict(g) for g in result.rings],
        "dims": dict(result.dims) if result.dims is not None else None,
    }


def live_roi_payload(
    *,
    counts: np.ndarray | None,
    ir_format: str | None,
    rois: list[dict[str, Any]],
    acquiring: bool,
    frame_id: int | None,
    host_ts_ns: int | None,
    now_ns: int,
    stale_ms: float = STALE_MS,
    smart: dict[int, SmartResult] | None = None,
) -> dict[str, Any]:
    """Per-ROI °C from the latest acquired frame, with an explicit freshness/validity contract.

    ``counts`` is the latest frame (uint16), or None when the camera has produced no frame.
    ``acquiring`` is whether the camera is actively streaming. Returns the JSON-able payload
    documented in the closed-loop design spec. ``smart`` holds the live trackers' latest
    results by ROI id (``SmartLive.latest()``); a smart ROI without one reports invalid.
    """
    age_ms = (now_ns - host_ts_ns) / 1e6 if host_ts_ns is not None else None
    have_frame = (
        acquiring and counts is not None and ir_format is not None and host_ts_ns is not None
    )
    stale = (not have_frame) or age_ms is None or age_ms > stale_ms
    live = bool(have_frame and not stale)

    payload: dict[str, Any] = {
        "live": live,
        "frame_id": frame_id if have_frame else None,
        "frame_ts": _iso(host_ts_ns) if (have_frame and host_ts_ns is not None) else None,
        "age_ms": round(age_ms, 1) if age_ms is not None else None,
        "stale": bool(stale),
        "rois": [],
    }

    celsius: np.ndarray | None = None
    if live and counts is not None and ir_format is not None:
        try:
            celsius = counts_to_celsius(counts, IRFormat(ir_format))
        except ValueError:  # unknown/unsupported IR format → cannot trust temperatures
            celsius = None

    if celsius is None:  # not live, or unconvertible: roster only, all invalid
        payload["live"] = False
        payload["stale"] = True
        payload["rois"] = [_invalid_roi(r) for r in rois]
        return payload

    over = over_range_mask(
        counts,  # type: ignore[arg-type]  # counts is not None here
        kelvin_per_count=kelvin_per_count(IRFormat(ir_format)))
    h, w = celsius.shape
    out: list[dict[str, Any]] = []
    for roi in rois:
        if roi.get("kind") == "smart":
            try:
                result = (smart or {}).get(roi.get("id"))  # type: ignore[arg-type]
                out.append(_smart_entry(roi, result, host_ts_ns))  # type: ignore[arg-type]
            except (KeyError, ValueError, TypeError, AttributeError):
                out.append(_invalid_roi(roi))  # a malformed result only invalidates itself
            continue
        try:
            ys, xs = roi_index(roi, w, h)
        except (KeyError, ValueError, TypeError, IndexError):
            # A malformed or half-drawn ROI must never take down the whole feed the RF controller
            # reads: report just that ROI invalid (null temps) and keep measuring the others.
            out.append(_invalid_roi(roi))
            continue
        if ys.size == 0:  # ROI off-frame / empty → nothing to measure
            out.append(_invalid_roi(roi))
            continue
        region_over = (
            over[ys, xs] if over is not None else np.zeros(ys.shape, dtype=bool)
        )
        if bool(region_over.any()):
            # Any saturated pixel makes the ROI's max (the over-temp guard) untrustworthy — fail
            # safe on the whole ROI rather than reporting an understated number.
            out.append(_invalid_roi(roi, over_range=True))
            continue
        region = celsius[ys, xs]
        mean_c = float(np.mean(region))
        out.append({
            "id": roi.get("id"), "name": roi.get("name"), "kind": roi.get("kind"),
            "mean_c": mean_c,
            "max_c": float(np.max(region)),
            "min_c": float(np.min(region)),
            "value_c": mean_c if roi.get("kind") == "spot" else None,
            "over_range": False,
            "valid": True,
        })
    payload["rois"] = out
    return payload


__all__ = ["live_roi_payload", "SMART_LAG_MS", "STALE_MS"]
