"""Region masks: include/exclude polygons and rectangles that pick the pixels used for the colour
auto-range and the frame statistics.

A mask never alters the thermal counts and is not an ROI: it produces no series and is not in
roi_series.csv. Pixel coverage matches the ROI kinds of the same name (rect half-open, polygon
even-odd interior plus boundary); the browser rasterises it.
"""

from __future__ import annotations

from typing import Any

MAX_MASKS = 32
MASK_MODES = ("include", "exclude")


def _num(v: Any, name: str) -> float | int:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"mask {name} must be a number")
    return v


def parse_masks(items: Any) -> list[dict[str, Any]]:
    """Validate a list of mask shapes; returns them unchanged (id, kind, geometry, mode)."""
    if not isinstance(items, list):
        raise ValueError("masks must be a list")
    if len(items) > MAX_MASKS:
        raise ValueError(f"at most {MAX_MASKS} masks")
    out: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            raise ValueError("each mask must be an object")
        mode = it.get("mode")
        if mode not in MASK_MODES:
            raise ValueError(f"mask mode must be one of {MASK_MODES}")
        mid = _num(it.get("id"), "id")
        kind = it.get("kind")
        if kind == "rect":
            geo = {k: _num(it.get(k), k) for k in ("x0", "y0", "x1", "y1")}
            out.append({"id": mid, "kind": "rect", **geo, "mode": mode})
        elif kind == "polygon":
            pts = it.get("points")
            if not isinstance(pts, list) or len(pts) < 3:
                raise ValueError("a polygon mask needs at least 3 points")
            clean = []
            for p in pts:
                if not isinstance(p, list) or len(p) != 2:
                    raise ValueError("polygon points must be [x, y] pairs")
                clean.append([_num(p[0], "x"), _num(p[1], "y")])
            out.append({"id": mid, "kind": "polygon", "points": clean, "mode": mode})
        else:
            raise ValueError("a mask must be a polygon or a rect")
    return out


def mask_desc(m: dict[str, Any]) -> str:
    """One README line: ``include: polygon points=[...]`` / ``exclude: rect x0=.. y0=.. ...``."""
    if m["kind"] == "rect":
        geo = f"rect x0={m['x0']} y0={m['y0']} x1={m['x1']} y1={m['y1']}"
    else:
        geo = f"polygon points={m['points']}"
    return f"{m['mode']}: {geo}"


__all__ = ["MASK_MODES", "MAX_MASKS", "mask_desc", "parse_masks"]
