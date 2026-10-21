"""Post-run analysis of the visible camera around the sample.

The A70's visible video clips the powder, but the sample stays well exposed. This module holds the
pure functions of that analysis: picking the sample (and bed) ROI, mapping its outline from IR
pixels into visible pixels, rasterising the analysis region, choosing the dark threshold,
measuring each frame, then finding the flash events in the brightening series and summarising how
completely the video covered the run. Nothing here touches the store or the video file.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from flir_research_interface.analysis.visible_overlay import ir_to_visible_coeffs

logger = logging.getLogger(__name__)

_AREA_KINDS = ("polygon", "rect", "circle", "ellipse")
_MAX_CANVAS_PX = 64_000_000  # largest polygon bounding box region_mask will rasterise
_MAD_SCALE = 1.4826  # scales the median absolute deviation to a normal distribution's sigma
_GAP_S = 0.3  # a spacing between analysed frames longer than this counts as a gap in coverage


def _area(roi: dict[str, Any]) -> float:
    """Area in IR pixels of an area-kind ROI (polygon by the shoelace formula)."""
    kind = roi["kind"]
    if kind == "rect":
        return abs(float(roi["x1"] - roi["x0"]) * float(roi["y1"] - roi["y0"]))
    if kind == "circle":
        return math.pi * float(roi["r"]) ** 2
    if kind == "ellipse":
        return math.pi * float(roi["rx"]) * float(roi["ry"])
    pts = np.asarray(roi["points"], dtype=float)
    x, y = pts[:, 0], pts[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def pick_rois(
    rois: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The ``(sample, bed)`` ROIs of a run, by name; ``None`` for one that is not there.

    The sample is the area ROI whose name contains "sample" (case-insensitive); with several, the
    smallest by area wins. The bed is the largest area ROI whose name contains "powder" or "bed".
    Only polygon, rect, circle and ellipse ROIs qualify; a spot or line named "sample" does not.
    """
    areas = [r for r in rois or [] if r.get("kind") in _AREA_KINDS]

    def named(*words: str) -> list[dict[str, Any]]:
        return [r for r in areas if any(w in str(r.get("name") or "").lower() for w in words)]

    samples, beds = named("sample"), named("powder", "bed")
    return (
        min(samples, key=_area) if samples else None,
        max(beds, key=_area) if beds else None,
    )


def roi_outline_ir(roi: dict[str, Any], n_circle: int = 64) -> np.ndarray:
    """The outline of an area ROI as an ``(N, 2)`` float array of IR pixel coordinates.

    A polygon keeps its vertices, a rect gives its four corners, and a circle or ellipse is
    sampled at ``n_circle`` evenly spaced angles. Other kinds raise ``ValueError``.
    """
    kind = roi["kind"]
    if kind == "polygon":
        return np.asarray(roi["points"], dtype=float).reshape(-1, 2)
    if kind == "rect":
        x0, y0, x1, y1 = (float(roi[k]) for k in ("x0", "y0", "x1", "y1"))
        return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=float)
    if kind in ("circle", "ellipse"):
        rx = float(roi["r"] if kind == "circle" else roi["rx"])
        ry = float(roi["r"] if kind == "circle" else roi["ry"])
        a = np.linspace(0.0, 2.0 * np.pi, n_circle, endpoint=False)
        return np.column_stack([roi["cx"] + rx * np.cos(a), roi["cy"] + ry * np.sin(a)])
    raise ValueError(f"ROI kind {kind!r} has no outline")


def ir_to_visible_points(
    points: np.ndarray,
    h_matrix: list[list[float]],
    ir_size: tuple[int, int] = (640, 480),
    vis_size: tuple[int, int] = (1280, 960),
) -> np.ndarray:
    """Map ``(N, 2)`` IR pixel coordinates to visible pixel coordinates.

    ``h_matrix`` is the stored visible-to-IR homography in normalised coordinates. The mapping is
    its inverse with the basis change of :func:`ir_to_visible_coeffs`, so it lands on the same
    visible pixels as the overlay export.
    """
    a, b, c, d, e, f, g, h = ir_to_visible_coeffs(
        h_matrix, ir_size[0], ir_size[1], vis_size[0], vis_size[1]
    )
    m = np.array([[a, b, c], [d, e, f], [g, h, 1.0]])
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    hom = np.c_[pts, np.ones(len(pts))] @ m.T
    return np.asarray(hom[:, :2] / hom[:, 2:3])


def _grow(mask: np.ndarray, margin: int) -> np.ndarray:
    """``mask`` grown by ``margin`` px: every pixel within Euclidean distance ``margin`` of a set
    pixel. The result is ``margin`` larger on each side, so its origin is ``(-margin, -margin)``
    from that of ``mask``."""
    h, w = mask.shape
    wide = np.zeros((h, w + 2 * margin), dtype=bool)
    wide[:, margin : margin + w] = mask
    runs = [wide]  # runs[k]: each row dilated by k px to the left and right
    for _ in range(margin):
        prev = runs[-1]
        nxt = prev.copy()
        nxt[:, 1:] |= prev[:, :-1]
        nxt[:, :-1] |= prev[:, 1:]
        runs.append(nxt)
    grown = np.zeros((h + 2 * margin, w + 2 * margin), dtype=bool)
    for dy in range(-margin, margin + 1):
        grown[margin + dy : margin + dy + h] |= runs[math.isqrt(margin * margin - dy * dy)]
    return grown


def _even_span(lo: int, size: int, limit: int) -> tuple[int, int]:
    """Widen the span ``[lo, lo + size)`` by one pixel if ``size`` is odd, within ``[0, limit)``."""
    if size % 2 == 0:
        return lo, size
    if lo + size < limit:
        return lo, size + 1
    if lo > 0:
        return lo - 1, size + 1
    return lo, size  # the span fills an odd-sized frame: there is no even span to give


def region_mask(
    outline_vis: np.ndarray,
    margin_px: int,
    vis_size: tuple[int, int] = (1280, 960),
) -> tuple[np.ndarray, tuple[int, int, int, int]] | None:
    """The analysis region of a visible frame: the outline's polygon grown by a margin.

    The polygon is rasterised with ``PIL.ImageDraw.polygon`` (boundary included), then grown by
    ``margin_px`` with a Euclidean distance test; parts outside the frame are dropped. Returns
    ``(mask, (x0, y0, w, h))``: a boolean mask cropped to the region's bounding box, widened to
    an even ``w`` and ``h`` (the video encoder wants even sizes), clipped to the frame. Returns
    ``None`` when no pixel of the grown region lies in the frame, or the outline is not finite.
    """
    pts = np.asarray(outline_vis, dtype=float).reshape(-1, 2)
    if len(pts) == 0 or not np.all(np.isfinite(pts)):
        return None
    vis_w, vis_h = vis_size
    m = max(0, int(margin_px))
    lo_f, hi_f = np.floor(pts.min(axis=0)), np.ceil(pts.max(axis=0))
    if np.prod(hi_f - lo_f + 1.0) > _MAX_CANVAS_PX:
        return None  # not a plausible sample region (e.g. a badly conditioned homography)
    lo, hi = lo_f.astype(int), hi_f.astype(int)
    # Polygon pixels more than m outside the frame cannot reach into it: grow only the window.
    win_lo = np.maximum(lo, -m)
    win_hi = np.minimum(hi, (vis_w - 1 + m, vis_h - 1 + m))
    if np.any(win_hi < win_lo):
        return None
    # Draw the whole polygon: PIL's raster of a polygon clipped by the canvas differs along the
    # clipped edge, so the result would depend on where the frame is.
    canvas = Image.new("1", (int(hi[0] - lo[0]) + 1, int(hi[1] - lo[1]) + 1), 0)
    ImageDraw.Draw(canvas).polygon(
        [(float(x - lo[0]), float(y - lo[1])) for x, y in pts], fill=1, outline=1
    )
    poly = np.asarray(canvas, dtype=bool)[
        win_lo[1] - lo[1] : win_hi[1] - lo[1] + 1, win_lo[0] - lo[0] : win_hi[0] - lo[0] + 1
    ]
    grown = _grow(poly, m)
    # grown[0, 0] sits at frame pixel (win_lo - m); keep the part inside the frame
    gx0, gy0 = int(win_lo[0]) - m, int(win_lo[1]) - m
    cx0, cy0 = max(0, gx0), max(0, gy0)
    cx1, cy1 = min(vis_w, gx0 + grown.shape[1]), min(vis_h, gy0 + grown.shape[0])
    if cx1 <= cx0 or cy1 <= cy0:
        return None
    inside = grown[cy0 - gy0 : cy1 - gy0, cx0 - gx0 : cx1 - gx0]
    ys, xs = np.nonzero(inside)
    if len(xs) == 0:
        return None
    tight = inside[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    tx0, ty0 = cx0 + int(xs.min()), cy0 + int(ys.min())
    bx0, bw = _even_span(tx0, tight.shape[1], vis_w)
    by0, bh = _even_span(ty0, tight.shape[0], vis_h)
    out = np.zeros((bh, bw), dtype=bool)
    out[ty0 - by0 : ty0 - by0 + tight.shape[0], tx0 - bx0 : tx0 - bx0 + tight.shape[1]] = tight
    return out, (bx0, by0, bw, bh)


def otsu_threshold(values: np.ndarray) -> int:
    """Otsu's threshold of 8-bit ``values``: the level 0-255 that maximises the between-class
    variance of a 256-bin histogram, with the lower class holding the levels up to and including it.

    Ties go to the lowest level. Values outside 0..255 are ignored; an input with no value in range
    raises ``ValueError``. An input of a single level has no two classes and gives 0.
    """
    hist, _ = np.histogram(values, bins=256, range=(0, 256))
    total = int(hist.sum())
    if total == 0:
        raise ValueError("otsu_threshold needs at least one value in 0..255")
    n_low = np.cumsum(hist)  # pixels at or below each level
    sum_low = np.cumsum(hist * np.arange(256))  # their summed levels
    n_high = total - n_low
    both = (n_low > 0) & (n_high > 0)  # only levels that leave both classes non-empty
    between = np.zeros(256)
    mean_low = sum_low[both] / n_low[both]
    mean_high = (sum_low[-1] - sum_low[both]) / n_high[both]
    between[both] = n_low[both] * n_high[both] * (mean_low - mean_high) ** 2
    return int(np.argmax(between))


@dataclass(frozen=True)
class FrameMetrics:
    """What one visible frame says about the sample.

    ``sample_dark_px`` counts region pixels darker than the run's threshold and ``sample_mean_luma``
    is their mean luma (``None`` when there are none). ``bed_clipped_frac`` is the fraction of the
    bed at 255 (``None`` without a bed). ``brightening`` is the 99.5th percentile of the change in
    luma over the region since the previous analysed frame (``None`` for the first one).
    """

    sample_dark_px: int
    sample_mean_luma: float | None
    bed_clipped_frac: float | None
    brightening: float | None


def frame_metrics(
    luma: np.ndarray,
    prev: np.ndarray | None,
    region: np.ndarray,
    threshold: int,
    bed: np.ndarray | None = None,
) -> FrameMetrics:
    """The :class:`FrameMetrics` of one frame.

    ``luma`` and ``prev`` are uint8 crops of one bounding box; ``region`` and ``bed`` are boolean
    masks of that box. A pixel is dark when its luma is strictly below ``threshold``. ``prev`` is
    the previous *analysed* frame of the same video segment (``None`` for a segment's first), so
    the frames of the start-up skip never serve as one. The luma change is taken in ``int16``.
    """
    in_region = luma[region]
    dark = in_region < threshold
    n_dark = int(np.count_nonzero(dark))
    mean_luma = float(in_region[dark].mean()) if n_dark else None
    clipped = float(np.mean(luma[bed] == 255)) if bed is not None and bed.any() else None
    brightening = None
    if prev is not None and in_region.size:
        change = in_region.astype(np.int16) - prev[region].astype(np.int16)
        brightening = float(np.percentile(change, 99.5))
    return FrameMetrics(n_dark, mean_luma, clipped, brightening)


def flash_threshold(
    brightening: np.ndarray,
    keyframe: np.ndarray,
    floor: float = 15.0,
    k: float = 6.0,
    mad_floor: float = 1.0,
) -> float:
    """The brightening level that flags a frame: ``max(floor, median + k * max(MAD, mad_floor))``.

    The median and MAD (scaled by 1.4826) are taken over the non-keyframe values; NaNs and
    keyframes (whose brightening is the encoder's refresh, not the scene) are ignored. Flooring the
    MAD keeps a near-silent run from flagging noise. With no value left, the result is ``floor``.
    """
    values = np.asarray(brightening, dtype=float)
    usable = values[~np.asarray(keyframe, dtype=bool) & ~np.isnan(values)]
    if usable.size == 0:
        return float(floor)
    median = float(np.median(usable))
    mad = _MAD_SCALE * float(np.median(np.abs(usable - median)))
    return float(max(floor, median + k * max(mad, mad_floor)))


def _event(t_s: np.ndarray, brightening: np.ndarray, frames: list[int]) -> dict[str, Any]:
    """The event made of flagged ``frames`` (array indices in time order); the peak is the frame
    with the largest brightening, the earliest of equals."""
    peak = frames[int(np.argmax(brightening[frames]))]
    return {
        "t_start_s": float(t_s[frames[0]]),
        "t_peak_s": float(t_s[peak]),
        "t_end_s": float(t_s[frames[-1]]),
        "peak_brightening": float(brightening[peak]),
        "n_frames": len(frames),
        "peak_frame": int(peak),
    }


def find_events(
    t_s: np.ndarray,
    brightening: np.ndarray,
    keyframe: np.ndarray,
    threshold: float,
    merge_s: float = 1.0,
) -> list[dict[str, Any]]:
    """The flash events of a run: flagged frames within ``merge_s`` of each other, merged.

    A frame is flagged when it is not a keyframe and its brightening is at least ``threshold``
    (NaN never is). ``t_s``, ``brightening`` and ``keyframe`` hold one row per frame in frame
    order, so ``t_s`` does not decrease. A flagged frame joins the open event when it comes no
    more than ``merge_s`` after the event's last flagged frame, so a run of flashes closer than
    that chains into one event. Each event is ``{"t_start_s", "t_peak_s", "t_end_s",
    "peak_brightening", "n_frames", "peak_frame"}``, where ``n_frames`` counts the flagged frames
    and ``peak_frame`` is the index into the arrays. The region of the peak is added by the caller.
    """
    times = np.asarray(t_s, dtype=float)
    values = np.asarray(brightening, dtype=float)
    flagged = np.flatnonzero((values >= threshold) & ~np.asarray(keyframe, dtype=bool))
    events: list[dict[str, Any]] = []
    frames: list[int] = []
    for i in flagged.tolist():
        if frames and times[i] - times[frames[-1]] > merge_s:
            events.append(_event(times, values, frames))
            frames = []
        frames.append(i)
    if frames:
        events.append(_event(times, values, frames))
    return events


def coverage(t_s: np.ndarray) -> dict[str, Any]:
    """How much of the run the analysed frames cover.

    ``t_s`` holds the thermal-axis time of each analysed frame in frame order. Returns
    ``{"frames_analysed", "t_first_s", "t_last_s", "gaps_over_300ms"}``: the frame count, the first
    and last time (``None`` for no frames) and the number of spacings between consecutive frames
    longer than 300 ms, where the camera throttled the stream.
    """
    times = np.asarray(t_s, dtype=float)
    if times.size == 0:
        return {"frames_analysed": 0, "t_first_s": None, "t_last_s": None, "gaps_over_300ms": 0}
    return {
        "frames_analysed": int(times.size),
        "t_first_s": float(times[0]),
        "t_last_s": float(times[-1]),
        "gaps_over_300ms": int(np.count_nonzero(np.diff(times) > _GAP_S)),
    }
