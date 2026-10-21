"""Smart ROI: a user-drawn search area inside which the hot sample's outline is found per frame.

This module holds the spec type and its validation; detection lives alongside it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

DEFAULT_RINGS_PX: tuple[int, ...] = (5, 10, 25)
SENSITIVITY_RANGE = (0.3, 0.7)


@dataclass(frozen=True)
class SmartRoiSpec:
    id: int
    name: str | None
    search: tuple[tuple[int, int], ...]
    rings_px: tuple[int, ...] = DEFAULT_RINGS_PX
    rule: Literal["relative", "fixed"] = "relative"
    fixed_c: float | None = None
    sensitivity: float = 0.5
    ring_emissivity: float | None = None


def _int(v: Any, name: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int | float) or not float(v).is_integer():
        raise ValueError(f"{name} must be an integer")
    return int(v)


def _number(v: Any, name: str) -> float:
    if isinstance(v, bool) or not isinstance(v, int | float):
        raise ValueError(f"{name} must be a number")
    return float(v)


def parse_smart_roi(raw: dict[str, Any]) -> SmartRoiSpec:
    """Validate a ``kind:"smart"`` ROI object; raises ``ValueError`` on bad input."""
    pts = raw.get("search")
    if not isinstance(pts, list) or len(pts) < 3:
        raise ValueError("smart ROI search area needs at least 3 points")
    search: list[tuple[int, int]] = []
    for p in pts:
        if not isinstance(p, list | tuple) or len(p) != 2:
            raise ValueError("smart ROI search points must be [x, y] pairs")
        search.append((_int(p[0], "x"), _int(p[1], "y")))

    rings_raw = raw.get("rings_px", DEFAULT_RINGS_PX)
    if not isinstance(rings_raw, list | tuple) or not rings_raw:
        raise ValueError("rings_px must be a non-empty list")
    rings = tuple(_int(r, "ring offset") for r in rings_raw)
    if rings[0] < 1 or any(b <= a for a, b in zip(rings, rings[1:], strict=False)):
        raise ValueError("rings_px must be positive and strictly increasing")

    rule = raw.get("rule", "relative")
    if rule not in ("relative", "fixed"):
        raise ValueError("rule must be 'relative' or 'fixed'")
    fixed_raw = raw.get("fixed_c")
    fixed_c = None if fixed_raw is None else _number(fixed_raw, "fixed_c")
    if rule == "fixed" and fixed_c is None:
        raise ValueError("rule 'fixed' needs fixed_c")

    sensitivity = _number(raw.get("sensitivity", 0.5), "sensitivity")
    lo, hi = SENSITIVITY_RANGE
    if not lo <= sensitivity <= hi:
        raise ValueError(f"sensitivity must be between {lo} and {hi}")

    eps_raw = raw.get("ring_emissivity")
    ring_emissivity = None if eps_raw is None else _number(eps_raw, "ring_emissivity")
    if ring_emissivity is not None and not 0.01 <= ring_emissivity <= 1.0:
        raise ValueError("ring_emissivity must be a number between 0.01 and 1")

    name = raw.get("name")
    if name is not None and not isinstance(name, str):
        raise ValueError("name must be a string")
    return SmartRoiSpec(
        id=_int(raw.get("id"), "id"),
        name=name,
        search=tuple(search),
        rings_px=rings,
        rule=rule,
        fixed_c=fixed_c,
        sensitivity=sensitivity,
        ring_emissivity=ring_emissivity,
    )
