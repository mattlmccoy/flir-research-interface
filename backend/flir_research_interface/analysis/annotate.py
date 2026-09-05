"""Publication-grade derived images: a frame rendered at 2x native resolution with the inferno
palette on a fixed run-wide scale, optionally with the stored ROIs drawn and labelled with their
value at that frame, plus a color bar and a caption. Used for ``exports/peak_frame*.png`` and,
per frame, for the annotated thermal video. Nothing here touches the store."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import numpy.typing as npt
from PIL import Image, ImageDraw, ImageFont

from flir_research_interface.analysis.series import roi_field, roi_index
from flir_research_interface.analysis.thermal_video import run_range
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.radiometry.colormaps import INFERNO_LUT
from flir_research_interface.radiometry.temperature_linear import IRFormat, counts_to_celsius

DEFAULT_COLORS = ("#ffb000", "#4cc9f0", "#ff8ad8", "#7cff6b", "#ff6b6b", "#c8a2ff", "#ffffff")
BAR_W = 28
CAPTION_H = 26


def _rgb(hexcol: str) -> tuple[int, int, int]:
    h = hexcol.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def colorize(values: npt.NDArray[np.float32], vmin: float, vmax: float) -> npt.NDArray[np.uint8]:
    span = vmax - vmin
    v = np.nan_to_num(values, nan=vmin)
    idx = (
        np.clip(np.rint((v - vmin) * (255.0 / span)), 0, 255).astype(np.uint8)
        if span > 0
        else np.full(v.shape, 128, dtype=np.uint8)
    )
    return INFERNO_LUT[idx]


def _font(size: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.load_default(size=size)
    if not isinstance(f, ImageFont.FreeTypeFont):  # pragma: no cover - Pillow < 10.1
        raise RuntimeError("Pillow >= 10.1 required")
    return f


_LABEL_GAP = 4  # keep a label this far from other labels


def _leader_anchor(r: dict[str, Any], s: float) -> tuple[float, float, float]:
    """(cx, cy, reach) a leader line can tie to: the ring edge for circles/ellipses, else the
    centre (reach 0). Mirrors the live overlay's roiLeaderAnchor so both renders match."""
    k = r["kind"]
    if k == "spot":
        return (r["x"] + 0.5) * s, (r["y"] + 0.5) * s, 0.0
    if k == "rect":
        return (r["x0"] + r["x1"]) / 2 * s, (r["y0"] + r["y1"]) / 2 * s, 0.0
    if k in ("circle", "ellipse"):
        rx = (r["r"] if k == "circle" else r["rx"]) * s
        ry = (r["r"] if k == "circle" else r["ry"]) * s
        return (r["cx"] + 0.5) * s, (r["cy"] + 0.5) * s, min(rx, ry)
    if k == "line":
        return ((r["x0"] + r["x1"]) / 2 + 0.5) * s, ((r["y0"] + r["y1"]) / 2 + 0.5) * s, 0.0
    pts = r["points"]
    return (sum(p[0] for p in pts) / len(pts) + 0.5) * s, \
           (sum(p[1] for p in pts) / len(pts) + 0.5) * s, 0.0


def _layout_labels(
    boxes: list[dict[str, float]], img_w: float, img_h: float, gap: float = _LABEL_GAP,
) -> list[dict[str, Any]]:
    """Greedy collision resolution (a port of the live overlay's layoutLabels): each box keeps its
    x, and its y is swept down/up to clear already-placed boxes sharing that column. A box that had
    to move is flagged ``displaced`` so the caller draws a leader line back to its ROI."""
    placed: list[dict[str, float]] = []
    out: list[dict[str, Any]] = []
    for b in boxes:
        x = min(max(0.0, b["ax"]), max(0.0, img_w - b["w"]))
        y = _resolve_y(x, b["ay"], b["w"], b["h"], placed, img_h, gap)
        placed.append({"x": x, "y": y, "w": b["w"], "h": b["h"]})
        out.append({"id": b["id"], "x": x, "y": y, "displaced": abs(y - b["ay"]) > 0.5})
    return out


def _resolve_y(x: float, ay: float, w: float, h: float, placed: list[dict[str, float]],
               img_h: float, gap: float) -> float:
    max_y = max(0.0, img_h - h)
    start = min(max(0.0, ay), max_y)
    rel = [r for r in placed if x < r["x"] + r["w"] and r["x"] < x + w]

    def sweep(down: bool) -> float:
        y = start
        for _ in range(len(rel) + 1):
            hit = next((r for r in rel if y < r["y"] + r["h"] + gap and r["y"] < y + h + gap), None)
            if hit is None:
                return y
            y = (hit["y"] + hit["h"] + gap) if down else (hit["y"] - h - gap)
            if y < 0 or y > max_y:
                break
        return y
    d1 = sweep(True)
    if 0 <= d1 <= max_y:
        return d1
    d2 = sweep(False)
    if 0 <= d2 <= max_y:
        return d2
    return start


def draw_rois(
    img: Image.Image,
    rois: list[dict[str, Any]],
    *,
    scale: float,
    values: dict[int, str] | None = None,
    width: int = 2,
) -> None:
    """Outline every ROI (sensor coordinates x ``scale``) in its color, with a label placed to
    avoid overlapping the other labels; a leader line ties a moved label back to its ROI so the
    labels do not sit on top of the shapes when there is room beside them."""
    d = ImageDraw.Draw(img, "RGBA")
    font = _font(max(11, int(7 * scale)))
    img_w, img_h = img.size

    bboxes = [_bbox(r, scale) for r in rois]
    boxes: list[dict[str, float]] = []
    meta: dict[int, dict[str, Any]] = {}
    for i, r in enumerate(rois):
        label = r.get("name") or f"{r['kind']} {r['id']}"
        if values and r["id"] in values:
            label = f"{label}  {values[r['id']]}"
        tw = d.textlength(label, font=font)
        w, h = tw + 4, font.size + 2
        tcx, tty = _shape_top(r, scale)  # centre the label above the shape's top edge
        ax = tcx - w / 2
        # lift above the TOPMOST shape sharing the label's x-range, so a label nested inside a
        # bigger ROI (e.g. concentric circles) rises above the whole cluster and uses a leader.
        top = min([tty] + [bt for (bl, bt, br, _bb) in bboxes if bl < ax + w and ax < br])
        boxes.append({"id": r["id"], "ax": ax, "ay": top - h - _LABEL_GAP, "w": w, "h": h})
        meta[r["id"]] = {"label": label, "w": w, "h": h,
                         "col": _rgb(r.get("color") or DEFAULT_COLORS[i % len(DEFAULT_COLORS)]),
                         "anchor": _leader_anchor(r, scale)}

    placed = _layout_labels(boxes, img_w, img_h)
    for pl in placed:  # leader lines under the labels, only for labels that had to move
        if not pl["displaced"]:
            continue
        m = meta[pl["id"]]
        dotx, doty = pl["x"] + m["w"] / 2, pl["y"] + m["h"] / 2
        cx, cy, reach = m["anchor"]
        tx, ty = cx, cy
        if reach > 0:
            ddx, ddy = dotx - cx, doty - cy
            dist = math.hypot(ddx, ddy) or 1.0
            tx, ty = cx + ddx / dist * reach, cy + ddy / dist * reach
        d.line([(tx, ty), (dotx, doty)], fill=(*m["col"], 150), width=1)
    for pl in placed:  # label boxes + text
        m = meta[pl["id"]]
        x, y = pl["x"], pl["y"]
        d.rectangle([x - 2, y - 1, x + m["w"], y + m["h"]], fill=(0, 0, 0, 160))
        d.text((x, y), m["label"], fill=m["col"], font=font)
    for i, r in enumerate(rois):  # outlines last, so an edge stays crisp even under a label
        _draw_one(d, r, i, scale, font, values, width)


def _bbox(r: dict[str, Any], s: float) -> tuple[float, float, float, float]:
    """(left, top, right, bottom) of a ROI in canvas px."""
    k = r["kind"]
    if k == "spot":
        x, y = (r["x"] + 0.5) * s, (r["y"] + 0.5) * s
        return x - 6, y - 6, x + 6, y + 6
    if k == "rect":
        return r["x0"] * s, r["y0"] * s, r["x1"] * s, r["y1"] * s
    if k in ("circle", "ellipse"):
        rx = (r["r"] if k == "circle" else r["rx"]) * s
        ry = (r["r"] if k == "circle" else r["ry"]) * s
        cx, cy = (r["cx"] + 0.5) * s, (r["cy"] + 0.5) * s
        return cx - rx, cy - ry, cx + rx, cy + ry
    if k == "line":
        return (min(r["x0"], r["x1"]) * s, min(r["y0"], r["y1"]) * s,
                max(r["x0"], r["x1"]) * s, max(r["y0"], r["y1"]) * s)
    pts = r["points"]
    xs = [p[0] * s for p in pts]
    ys = [p[1] * s for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _shape_top(r: dict[str, Any], s: float) -> tuple[float, float]:
    """(centre_x, top_y) of a ROI in canvas px — so a label can sit centred just above the shape."""
    k = r["kind"]
    if k == "spot":
        return (r["x"] + 0.5) * s, (r["y"] + 0.5) * s - 8
    if k == "rect":
        return (r["x0"] + r["x1"]) / 2 * s, r["y0"] * s
    if k in ("circle", "ellipse"):
        ry = (r["r"] if k == "circle" else r["ry"]) * s
        return (r["cx"] + 0.5) * s, (r["cy"] + 0.5) * s - ry
    if k == "line":
        return (r["x0"] + r["x1"]) / 2 * s, min(r["y0"], r["y1"]) * s
    pts = r["points"]
    return sum(p[0] for p in pts) / len(pts) * s, min(p[1] for p in pts) * s


def _draw_one(
    d: ImageDraw.ImageDraw,
    r: dict[str, Any],
    i: int,
    s: float,
    font: ImageFont.FreeTypeFont,
    values: dict[int, str] | None,
    width: int,
    outline: bool = True,
) -> None:
    """Stroke one ROI's outline in its color (labels are placed separately by draw_rois)."""
    col = _rgb(r.get("color") or DEFAULT_COLORS[i % len(DEFAULT_COLORS)])
    k = r["kind"]
    if k == "spot":
        x, y = (r["x"] + 0.5) * s, (r["y"] + 0.5) * s
        d.line([(x - 6, y), (x + 6, y)], fill=col, width=width)
        d.line([(x, y - 6), (x, y + 6)], fill=col, width=width)
    elif k == "rect":
        box = [r["x0"] * s, r["y0"] * s, r["x1"] * s - 1, r["y1"] * s - 1]
        d.rectangle(box, outline=col, width=width)
    elif k in ("circle", "ellipse"):
        rx = (r["r"] if k == "circle" else r["rx"]) * s
        ry = (r["r"] if k == "circle" else r["ry"]) * s
        cx, cy = (r["cx"] + 0.5) * s, (r["cy"] + 0.5) * s
        d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], outline=col, width=width)
    elif k == "line":
        a = ((r["x0"] + 0.5) * s, (r["y0"] + 0.5) * s)
        b = ((r["x1"] + 0.5) * s, (r["y1"] + 0.5) * s)
        d.line([a, b], fill=col, width=width)
    else:  # polygon / polyline
        pts = [((x + 0.5) * s, (y + 0.5) * s) for x, y in r["points"]]
        d.line(pts + ([pts[0]] if k == "polygon" else []), fill=col, width=width)


def _celsius(reader: ExperimentReader, index: int) -> npt.NDArray[np.float32]:
    fr = reader.frame(index)
    fmt = reader.ir_format or ""
    if fmt in ("TemperatureLinear10mK", "TemperatureLinear100mK"):
        return np.asarray(counts_to_celsius(fr.counts, IRFormat(fmt)), dtype=np.float32)
    return fr.counts.astype(np.float32)


def roi_values_at(
    reader: ExperimentReader, celsius: npt.NDArray[np.float32], rois: list[dict[str, Any]]
) -> dict[int, str]:
    """'mean' for areas, value for spots, with per-ROI optics applied, formatted in °C."""
    out: dict[int, str] = {}
    h, w = celsius.shape
    cam = reader.metadata.get("camera")
    for r in rois:
        field = roi_field(celsius[None, :, :], r, cam, True)[0]
        if r["kind"] == "spot":
            x, y = int(r["x"]), int(r["y"])
            if r.get("box") == 3:
                sub = field[max(0, y - 1) : y + 2, max(0, x - 1) : x + 2]
                v = float(np.nanmean(sub)) if sub.size else float("nan")
            else:
                v = float(field[y, x]) if 0 <= x < w and 0 <= y < h else float("nan")
        elif r["kind"] == "rect":
            sub = field[max(0, r["y0"]) : min(h, r["y1"]), max(0, r["x0"]) : min(w, r["x1"])]
            v = float(np.nanmean(sub)) if sub.size else float("nan")
        else:
            ys, xs = roi_index(r, w, h)
            v = float(np.nanmean(field[ys, xs])) if len(ys) else float("nan")
        out[r["id"]] = "n/a" if np.isnan(v) else f"{v:.1f} °C"
    return out


def annotated_frame(
    reader: ExperimentReader,
    index: int,
    *,
    scale: int = 2,
    with_rois: bool = True,
    vrange: tuple[float, float] | None = None,
    caption: str | None = None,
) -> Image.Image:
    """One frame at ``scale``x native resolution with color bar and caption; ROIs optional."""
    c = _celsius(reader, index)
    if vrange is not None:
        vmin, vmax = vrange
    else:  # robust scale of this frame: a single hot pixel must not crush the rest to black
        finite = c[np.isfinite(c)]
        if finite.size:
            vmin, vmax = float(np.percentile(finite, 0.5)), float(np.percentile(finite, 99.95))
            if vmax - vmin < 1.0:
                vmin, vmax = run_range(reader)[:2]
        else:
            vmin, vmax = run_range(reader)[:2]
    rgb = colorize(c, vmin, vmax)
    h, w = c.shape
    img = Image.fromarray(rgb).resize((w * scale, h * scale), Image.Resampling.NEAREST)
    rois = reader.metadata.get("rois") or []
    if with_rois and rois:
        draw_rois(img, rois, scale=scale, values=roi_values_at(reader, c, rois))
    # color bar
    bar_h = h * scale
    ramp = np.linspace(255, 0, bar_h).astype(np.uint8)
    bar = Image.fromarray(np.repeat(INFERNO_LUT[ramp][:, None, :], BAR_W, axis=1))
    font = _font(max(12, 6 * scale))
    out = Image.new("RGB", (w * scale + BAR_W + 70, bar_h + CAPTION_H), (12, 14, 18))
    out.paste(img, (0, 0))
    out.paste(bar, (w * scale + 8, 0))
    d = ImageDraw.Draw(out)
    for frac, lab in ((0.0, vmax), (0.5, (vmin + vmax) / 2), (1.0, vmin)):
        y = int(frac * (bar_h - 1))
        d.text(
            (w * scale + BAR_W + 12, max(0, min(bar_h - font.size, y - font.size // 2))),
            f"{lab:.1f} °C",
            fill=(230, 230, 230),
            font=font,
        )
    cap = (
        caption
        or f"{reader.path.name} · frame {index + 1}/{reader.n_frames}"
        f" · t = {reader.t_s(index):.2f} s · inferno {vmin:.1f} to {vmax:.1f} °C"
    )
    d.text((6, bar_h + 5), cap, fill=(200, 200, 200), font=_font(max(11, 5 * scale)))
    return out


def peak_index(reader: ExperimentReader) -> int:
    """Index of the frame containing the run's hottest pixel (first occurrence)."""
    best, best_i = -np.inf, 0
    for s in range(0, reader.n_frames, 64):
        block = reader.counts_block(s, min(s + 64, reader.n_frames))
        m = block.reshape(block.shape[0], -1).max(axis=1)
        j = int(m.argmax())
        if m[j] > best:
            best, best_i = m[j], s + j
    return best_i


def write_annotated_frames(reader: ExperimentReader, *, scale: int = 2) -> dict[str, Any]:
    """exports/peak_frame.png (clean) and exports/peak_frame_rois.png (annotated)."""
    out_dir = reader.path / "exports"
    out_dir.mkdir(exist_ok=True)
    idx = peak_index(reader)
    clean = out_dir / "peak_frame.png"
    rois = out_dir / "peak_frame_rois.png"
    annotated_frame(reader, idx, scale=scale, with_rois=False).save(clean, optimize=True)
    annotated_frame(reader, idx, scale=scale, with_rois=True).save(rois, optimize=True)
    return {"peak_index": idx, "peak_clean": str(clean), "peak_rois": str(rois)}


__all__ = ["annotated_frame", "draw_rois", "peak_index", "roi_values_at", "write_annotated_frames"]
