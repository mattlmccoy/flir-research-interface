"""Smart ROI: a user-drawn search area inside which the hot sample's outline is found per frame.

This module holds the spec type and its validation, and the pure per-frame detector/tracker
(``SmartTracker``): edge level, connected region, lock/hold/search states, rings and dimensions.
All work happens on a crop around the current search area so a 640x480 frame stays cheap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import numpy.typing as npt
from scipy import ndimage

HOLD_S = 1.0  # a failed frame keeps the last outline (valid, "holding") this long, then searches
SEARCH_MARGIN_PX = 15  # extra margin round the outline (beyond the outermost ring) to search in
MIN_CONTRAST_C = 2.0  # core (p99) minus surroundings (p20) of the search area
MIN_AREA_PX = 20
MAX_AREA_JUMP = 0.35  # fractional area change vs the previous lock allowed in one frame
LOCK_PASSES = 3  # lock-frame refinement passes (band-median rule) ...
LOCK_SETTLE = 0.01  # ... until the area changes less than this between passes
_HOT_PCT, _COLD_PCT = 99.0, 20.0  # core of the sample; drawn-outline surroundings

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


# --- detector / tracker -------------------------------------------------------------------------

State = Literal["searching", "locked", "holding"]
Box = tuple[int, int, int, int]  # x0, y0, x1, y1 half-open, frame coordinates
BoolArr = npt.NDArray[np.bool_]
FloatArr = npt.NDArray[np.float64]
# inputs to SmartTracker._measure: sample, work box, sample °C, ring °C, over-range, edge level
_Step = tuple[BoolArr, Box, FloatArr, FloatArr, BoolArr, float | None]


@dataclass
class SmartResult:
    """One frame's outcome. ``labels`` is a uint8 crop of ``bbox``: 0 none, 1 sample, 2.. ring i-2.
    Temperatures are ``None`` when not measured (searching) or when over-range pixels make them
    untrustworthy (``over_range``)."""

    state: State
    valid: bool
    bbox: Box | None = None
    labels: npt.NDArray[np.uint8] | None = None
    sample: dict[str, float | None] = field(default_factory=dict)
    rings: list[dict[str, Any]] = field(default_factory=list)
    dims: dict[str, Any] | None = None
    edge_level_c: float | None = None
    over_range: bool = False
    # host timestamp (ns) of the frame this result measured; set by the live path so the feed can
    # refuse a result left behind by a failed frame (None = unknown provenance)
    frame_ts_ns: int | None = None


def _no_stats() -> dict[str, float | None]:
    return {"mean_c": None, "max_c": None, "min_c": None}


def _stats(vals: FloatArr, over: bool) -> dict[str, float | None]:
    vals = vals[np.isfinite(vals)]
    if over or vals.size == 0:
        return _no_stats()
    return {"mean_c": float(vals.mean()), "max_c": float(vals.max()), "min_c": float(vals.min())}


def _bbox(mask: BoolArr, ox: int = 0, oy: int = 0) -> Box | None:
    rows, cols = np.flatnonzero(mask.any(axis=1)), np.flatnonzero(mask.any(axis=0))
    if rows.size == 0:
        return None
    return ox + int(cols[0]), oy + int(rows[0]), ox + int(cols[-1]) + 1, oy + int(rows[-1]) + 1


def _pad(box: Box, pad: int, w: int, h: int) -> Box:
    x0, y0, x1, y1 = box
    return max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)


def _place(mask: BoolArr, at: Box, into: Box) -> BoolArr:
    """``mask`` (covering box ``at``) re-cut to box ``into`` (outside ``at`` is False)."""
    x0, y0, x1, y1 = into
    out = np.zeros((y1 - y0, x1 - x0), dtype=bool)
    ax0, ay0, ax1, ay1 = at
    cx0, cy0, cx1, cy1 = max(x0, ax0), max(y0, ay0), min(x1, ax1), min(y1, ay1)
    if cx1 > cx0 and cy1 > cy0:
        out[cy0 - y0 : cy1 - y0, cx0 - x0 : cx1 - x0] = mask[
            cy0 - ay0 : cy1 - ay0, cx0 - ax0 : cx1 - ax0
        ]
    return out


def _dilate(mask: BoolArr, r: int) -> BoolArr:
    """Pixels within Euclidean distance ``r`` of ``mask`` (same shape; caller pads)."""
    return np.asarray(ndimage.distance_transform_edt(~mask) <= r, dtype=bool)


def _edge(mask: BoolArr, crop_border_inside: bool = False) -> BoolArr:
    """Pixels of ``mask`` with a 4-neighbour outside it. The crop border counts as outside unless
    ``crop_border_inside`` (then a mask cut off by the frame edge has no boundary there)."""
    inner = ndimage.binary_erosion(
        mask,
        structure=ndimage.generate_binary_structure(2, 1),
        border_value=1 if crop_border_inside else 0,
    )
    return np.asarray(mask & ~inner, dtype=bool)


def _dims(sample: BoolArr, x0: int, y0: int, field_c: FloatArr) -> dict[str, Any]:
    ys, xs = np.nonzero(sample)
    pts = np.stack([xs + x0, ys + y0]).astype(np.float64)
    centroid = pts.mean(axis=1)
    centred = pts - centroid[:, None]
    if xs.size > 1:
        _, vecs = np.linalg.eigh(np.cov(centred))
        proj = vecs.T @ centred  # row 0 = minor axis, row 1 = major axis
        ext = proj.max(axis=1) - proj.min(axis=1) + 1.0
        width, length = float(ext[0]), float(ext[1])
    else:
        width = length = 1.0
    edge = _edge(sample)
    gy, gx = np.gradient(field_c)
    grad = np.hypot(gx, gy)[edge]
    grad = grad[np.isfinite(grad)]
    return {
        "area_px": int(xs.size),
        "length_px": length,
        "width_px": width,
        "perimeter_px": int(edge.sum()),
        "centroid_x": float(centroid[0]),
        "centroid_y": float(centroid[1]),
        "sharpness_c_per_px": float(grad.mean()) if grad.size else None,
        "units": "px",
    }


class SmartTracker:
    """Per-frame outline finder for one smart ROI. Not thread-safe; one instance per ROI/stream.

    ``update`` takes the camera's °C field (``cam``/``optics`` re-correct it like other ROIs: the
    sample with the ROI's own emissivity, the rings with ``spec.ring_emissivity``) and the frame's
    over-range mask.
    """

    def __init__(
        self,
        spec: SmartRoiSpec,
        width: int,
        height: int,
        *,
        cam: dict[str, Any] | None = None,
        optics: dict[str, Any] | None = None,
    ) -> None:
        from flir_research_interface.analysis.series import roi_index  # series imports us

        self.spec, self.w, self.h = spec, width, height
        self._cam = cam
        self._optics = {
            k: v for k, v in (optics or {}).items() if k in ("emissivity", "reflected_c")
        }
        user = np.zeros((height, width), dtype=bool)
        ys, xs = roi_index(
            {"kind": "polygon", "points": [list(p) for p in spec.search]}, width, height
        )
        user[ys, xs] = True
        self._user = user
        self._user_box = _bbox(user)
        cap = np.zeros_like(user)
        if self._user_box is not None:
            cb = _pad(self._user_box, SEARCH_MARGIN_PX + 1, width, height)
            cap[cb[1] : cb[3], cb[0] : cb[2]] = _dilate(
                user[cb[1] : cb[3], cb[0] : cb[2]], SEARCH_MARGIN_PX
            )
        self._cap = cap
        self.reset()

    def reset(self) -> None:
        """Forget the track and the % change baseline (new run or changed spec)."""
        self._state: State = "searching"
        self._outline: BoolArr | None = None  # last good sample mask, cut to ``_outline_box``
        self._outline_box: Box | None = None
        self._last_good_t = 0.0
        self._last_area = 0
        self._baseline: dict[str, float] | None = None
        self._level: float | None = None
        self._work: Box = (0, 0, 0, 0)

    # -- per frame ---------------------------------------------------------------------------

    def _search(self) -> tuple[BoolArr, BoolArr | None, Box] | None:
        """(search mask, cold band or None, their box). The band — the shell (max ring, max ring
        + margin] outside the last outline — is where the surroundings are read while tracking."""
        if self._outline is None or self._outline_box is None:
            if self._user_box is None:
                return None
            b = self._user_box
            return self._user[b[1] : b[3], b[0] : b[2]], None, b
        ring = max(self.spec.rings_px)
        r = ring + SEARCH_MARGIN_PX
        b = _pad(self._outline_box, r + 1, self.w, self.h)
        dist = ndimage.distance_transform_edt(~_place(self._outline, self._outline_box, b))
        mask = np.asarray(dist <= r, dtype=bool)
        band: BoolArr | None = None
        if self._state == "searching":  # re-lock: never wander far from where the user drew
            mask &= self._cap[b[1] : b[3], b[0] : b[2]]
        else:
            band = np.asarray(dist > ring, dtype=bool) & mask
        sb = _bbox(mask)
        if sb is None:
            return None
        cut = (slice(sb[1], sb[3]), slice(sb[0], sb[2]))
        box = (b[0] + sb[0], b[1] + sb[1], b[0] + sb[2], b[1] + sb[3])
        return mask[cut], None if band is None else band[cut], box

    def _user_cold(
        self, celsius: npt.NDArray[Any], over: npt.NDArray[np.bool_] | None
    ) -> float | None:
        """p20 of the drawn outline (over-range excluded): the surroundings before a lock."""
        if self._user_box is None:
            return None
        x0, y0, x1, y1 = self._user_box
        field_c, _ = self._fields(np.asarray(celsius[y0:y1, x0:x1], dtype=np.float64))
        use = self._user[y0:y1, x0:x1] & np.isfinite(field_c)
        if over is not None:
            use &= ~np.asarray(over[y0:y1, x0:x1], dtype=bool)
        vals = field_c[use]
        return float(np.percentile(vals, _COLD_PCT)) if vals.size else None

    def _fields(self, crop: FloatArr) -> tuple[FloatArr, FloatArr]:
        from flir_research_interface.analysis.series import roi_field  # series imports us

        sample = roi_field(crop, self._optics, self._cam, True)
        if self.spec.ring_emissivity is None:
            return sample, sample
        ring_roi = {**self._optics, "emissivity": self.spec.ring_emissivity}
        return sample, roi_field(crop, ring_roi, self._cam, True)

    def _choose(self, candidates: BoolArr) -> BoolArr | None:
        """The connected region of ``candidates`` with the largest overlap with the previous
        outline (the largest region on a first lock, or when none overlaps)."""
        labels, n = ndimage.label(candidates)
        if n == 0:
            return None
        k = 0
        if self._outline is not None and self._outline_box is not None:
            prev = _place(self._outline, self._outline_box, self._work)
            overlap = np.bincount(labels[prev], minlength=n + 1)[1:]
            if overlap.max() > 0:
                k = int(overlap.argmax()) + 1
        if k == 0:
            k = int(np.bincount(labels.ravel(), minlength=n + 1)[1:].argmax()) + 1
        return np.asarray(labels == k, dtype=bool)

    def _detect(
        self, field_c: FloatArr, search: BoolArr, bad: BoolArr, cold: float | None
    ) -> tuple[BoolArr | None, float | None]:
        """(sample mask or None if this frame fails the checks, edge level). ``hot`` is the p99 of
        the chosen region itself, so neither the background share of the search area nor a hotter
        neighbour inside it moves the sample's edge."""
        usable = search & ~bad
        vals = field_c[usable]
        if vals.size == 0 or cold is None:
            return None, None
        s = self.spec.sensitivity
        fixed = self.spec.fixed_c if self.spec.rule == "fixed" else None
        top = float(np.percentile(vals, _HOT_PCT))
        level = float(fixed) if fixed is not None else cold + s * (top - cold)
        comp = self._choose(usable & (field_c >= level))  # provisional region
        if comp is None:
            return None, level
        hot = float(np.percentile(field_c[comp], _HOT_PCT))
        if hot - cold < MIN_CONTRAST_C:
            return None, level
        if fixed is None:
            level = cold + s * (hot - cold)
            comp = self._choose(usable & (field_c >= level))
            if comp is None:
                return None, level
        area = int(comp.sum())
        if area < MIN_AREA_PX or bool((comp & _edge(search, crop_border_inside=True)).any()):
            return None, level
        sample = np.asarray(ndimage.binary_fill_holes(comp), dtype=bool)
        area = int(sample.sum())
        jump = abs(area / self._last_area - 1.0) if self._last_area else 0.0
        if self._state != "searching" and jump > MAX_AREA_JUMP:
            return None, level
        return sample, level

    def update(
        self, celsius: npt.NDArray[Any], t_s: float, over: npt.NDArray[np.bool_] | None = None
    ) -> SmartResult:
        """Find the sample in this frame (or hold / search) and measure it."""
        if self._state != "searching" and t_s - self._last_good_t > HOLD_S:
            self._state = "searching"  # the last lock is stale: search again from this frame
        relock = self._state == "searching"
        step = self._step(celsius, t_s, over)
        if relock and step is not None and self._state == "locked":
            step = self._refine_lock(step, celsius, t_s, over)
        if step is None:
            return self._lost(self._level)
        return self._measure(*step)

    def _refine_lock(
        self,
        step: _Step,
        celsius: npt.NDArray[Any],
        t_s: float,
        over: npt.NDArray[np.bool_] | None,
    ) -> _Step:
        """Re-detect the lock frame with the tracking rule (cold = band median round the
        provisional outline) until the area settles, so the lock frame and the frames after it
        use the same estimator. A failed pass leaves the previous pass standing."""
        for _ in range(LOCK_PASSES):
            area = self._last_area
            saved = (self._outline, self._outline_box, self._level)
            self._last_area = 0  # no jump check between passes
            again = self._step(celsius, t_s, over)
            if again is None or self._state != "locked":
                self._state, self._last_area = "locked", area
                self._outline, self._outline_box, self._level = saved
                return step
            step = again
            if abs(self._last_area - area) < LOCK_SETTLE * area:
                break
        return step

    def _step(
        self, celsius: npt.NDArray[Any], t_s: float, over: npt.NDArray[np.bool_] | None
    ) -> _Step | None:
        """Detect and advance the state; the inputs to ``_measure``, or None when searching."""
        self._level = None
        found = self._search()
        if found is None:
            self._state = "searching"
            return None
        search_c, band_c, sbox = found
        work = self._work = _pad(sbox, max(self.spec.rings_px) + 1, self.w, self.h)
        x0, y0, x1, y1 = work
        search = _place(search_c, sbox, work)
        sample_c, ring_c = self._fields(np.asarray(celsius[y0:y1, x0:x1], dtype=np.float64))
        over_c = (
            np.zeros(search.shape, dtype=bool)
            if over is None
            else np.asarray(over[y0:y1, x0:x1], dtype=bool)
        )
        bad = over_c | ~np.isfinite(sample_c)
        cold: float | None = None
        if band_c is not None:  # tracking: median of the shell outside the last outline
            band = _place(band_c, sbox, work) & ~bad
            if band.any():
                cold = float(np.median(sample_c[band]))
        if cold is None:
            cold = self._user_cold(celsius, over)
        sample, self._level = self._detect(sample_c, search, bad, cold)
        if sample is not None:
            self._state, self._last_good_t, self._last_area = "locked", t_s, int(sample.sum())
            sb = _bbox(sample)
            assert sb is not None  # area >= MIN_AREA_PX
            self._outline = sample[sb[1] : sb[3], sb[0] : sb[2]].copy()
            self._outline_box = (x0 + sb[0], y0 + sb[1], x0 + sb[2], y0 + sb[3])
        elif self._state == "searching" or self._outline is None or self._outline_box is None:
            self._state = "searching"
            return None
        else:
            self._state = "holding"
            sample = _place(self._outline, self._outline_box, work)
        return sample, work, sample_c, ring_c, over_c, self._level

    def _lost(self, level: float | None) -> SmartResult:
        rings = [
            {"inner_px": a, "outer_px": b, **_no_stats()}
            for a, b in zip((0, *self.spec.rings_px), self.spec.rings_px, strict=False)
        ]
        return SmartResult("searching", False, sample=_no_stats(), rings=rings, edge_level_c=level)

    def _measure(
        self,
        sample: BoolArr,
        work: Box,
        sample_c: FloatArr,
        ring_c: FloatArr,
        over_c: BoolArr,
        level: float | None,
    ) -> SmartResult:
        x0, y0 = work[0], work[1]
        dist = ndimage.distance_transform_edt(~sample)
        labels = np.where(sample, 1, 0).astype(np.uint8)
        rings: list[dict[str, Any]] = []
        inner = 0
        for i, outer in enumerate(self.spec.rings_px):
            band = (dist > inner) & (dist <= outer)
            labels[band] = i + 2
            stats = _stats(ring_c[band], bool(over_c[band].any()))
            rings.append({"inner_px": inner, "outer_px": outer, **stats})
            inner = outer
        over = bool(over_c[sample].any())
        dims = _dims(sample, x0, y0, sample_c)
        if self._baseline is None:
            self._baseline = {k: dims[k] for k in ("area_px", "length_px", "width_px")}
        for k in ("area", "length", "width"):
            base = self._baseline[f"{k}_px"]
            dims[f"{k}_change_pct"] = (dims[f"{k}_px"] / base - 1.0) * 100.0 if base else None
        lb = _bbox(labels > 0)
        assert lb is not None  # the sample is never empty here
        return SmartResult(
            state=self._state,
            valid=not over,
            bbox=(x0 + lb[0], y0 + lb[1], x0 + lb[2], y0 + lb[3]),
            labels=labels[lb[1] : lb[3], lb[0] : lb[2]].copy(),
            sample=_stats(sample_c[sample], over),
            rings=rings,
            dims=dims,
            edge_level_c=level,
            over_range=over,
        )
