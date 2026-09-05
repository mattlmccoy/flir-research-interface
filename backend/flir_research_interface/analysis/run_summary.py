"""Per-run human-readable summary: ``README.txt`` (plain prose) and ``exports/roi_plot.png``.

Both are derived and regenerable; nothing here touches the store. The README is written for a
person opening the folder in a year: what was recorded, with which settings, and which file holds
what. The plot draws every stored ROI's trace (spot value, or mean with a min–max band) against
time with the operator's marks, using Pillow only (no matplotlib dependency on the operator).
"""

from __future__ import annotations

import io
import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from flir_research_interface.analysis.export import _roi_desc
from flir_research_interface.analysis.series import roi_series
from flir_research_interface.playback.reader import ExperimentReader

PLOT_W, PLOT_H = 2400, 1000  # 2x: crisp at slide/paper size
MARGIN_L, MARGIN_R, MARGIN_T, MARGIN_B = 140, 40, 60, 100
DEFAULT_COLORS = ("#ffb000", "#4cc9f0", "#ff8ad8", "#7cff6b", "#ff6b6b", "#c8a2ff", "#ffffff")


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


def _kelvin_to_c(v: Any) -> str:
    try:
        return f"{float(v) - 273.15:.1f} °C"
    except (TypeError, ValueError):
        return str(v)


def readme_text(reader: ExperimentReader) -> str:
    """Plain-prose description of the recording and its files."""
    m = reader.metadata
    cam = m.get("camera") or {}
    conv = m.get("conversion") or {}
    exp = m.get("experiment") or {}
    man = reader.manifest or {}
    lines: list[str] = []
    name = exp.get("name") or reader.path.name
    lines.append(f"Recording: {name}")
    lines.append(f"Folder: {reader.path.name}")
    if m.get("started_utc"):
        lines.append(f"Started (UTC): {m['started_utc']}")
    dur = reader.info()["duration_s"]
    lines.append(
        f"Length: {reader.n_frames} frames, {dur:.1f} s"
        + (f", recorded at {cam['frame_rate_hz']:g} fps" if cam.get("frame_rate_hz") else "")
        + (", complete" if man.get("complete") else ", NOT marked complete (see manifest.json)")
    )
    lines.append("")
    lines.append("Camera")
    lines.append(
        f"  {cam.get('vendor', 'FLIR')} {cam.get('model', '?')}, serial {cam.get('serial', '?')}"
        + (f", firmware {cam['firmware']}" if cam.get("firmware") else "")
        + (f", lens {cam['lens']}" if cam.get("lens") else "")
        + f", {cam.get('width', '?')}x{cam.get('height', '?')} pixels"
    )
    case = cam.get("active_case") or {}
    if case:
        lines.append(
            f"  Measurement case {case.get('index')}: "
            f"{case.get('low_c', float('nan')):.0f} to {case.get('high_c', float('nan')):.0f} °C"
        )
    op = cam.get("object_parameters") or {}
    if op:
        parts = []
        if "ObjectEmissivity" in op:
            parts.append(f"emissivity {float(op['ObjectEmissivity']):.3g}")
        if "ReflectedTemperature" in op:
            parts.append(f"reflected {_kelvin_to_c(op['ReflectedTemperature'])}")
        if "AtmosphericTemperature" in op:
            parts.append(f"atmosphere {_kelvin_to_c(op['AtmosphericTemperature'])}")
        if "ObjectDistance" in op:
            parts.append(f"distance {float(op['ObjectDistance']):.3g} m")
        if "RelativeHumidity" in op:
            parts.append(f"humidity {float(op['RelativeHumidity']) * 100:.0f} %")
        lines.append("  Object parameters: " + ", ".join(parts))
    if cam.get("device_temperature_c") is not None:
        stop = next((e for e in reader.events if e.get("type") == "camera_state"), None)
        t0 = float(cam["device_temperature_c"])
        t1 = stop.get("device_temperature_c") if stop else None
        lines.append(
            f"  Camera internal temperature: {t0:.1f} °C at start"
            + (f", {float(t1):.1f} °C at stop" if isinstance(t1, int | float) else "")
        )
    lines.append(
        f"  Pixel data: {cam.get('pixel_format', 'Mono16')} counts, IR format "
        f"{conv.get('ir_format') or cam.get('ir_format') or '?'}"
    )
    if conv.get("kelvin_per_count") is not None:
        lines.append(
            f"  Temperature rule: T_C = counts * {conv['kelvin_per_count']:g} - "
            f"{conv['kelvin_offset']:g}"
        )
    lines.append("")
    lines.append("Experiment fields")
    fields = {k: v for k, v in exp.items() if k != "name"}
    if fields:
        for k, v in fields.items():
            lines.append(f"  {k}: {_fmt(v)}")
    else:
        lines.append("  (none entered)")
    rois = m.get("rois") or []
    lines.append("")
    lines.append(f"Regions of interest at record time: {len(rois)}")
    for r in rois:
        label = r.get("name") or f"{r['kind']} {r['id']}"
        lines.append(f"  {label}: {_roi_desc(r)}")
    marks = [e for e in reader.events if e.get("type") == "annotation"]
    lines.append("")
    lines.append(f"Operator marks: {len(marks)}")
    for e in marks:
        lines.append(
            f"  {e.get('name')} at frame {e.get('frame_id')}"
            + (f" ({e['note']})" if e.get("note") else "")
        )
    lines.append("")
    lines.append(f"Visible camera video: {'yes (visible.mp4)' if reader.visible else 'no'}")
    lines.append(f"Visible-IR alignment stored: {'yes' if m.get('visible_alignment') else 'no'}")
    lines.append("")
    lines.append("Files")
    lines.append("  thermal.zarr/          every frame as raw uint16 counts (lossless); the record")
    lines.append("  metadata.json          all settings above in full, machine-readable")
    lines.append(
        "  events.json            start/stop, gaps, NUCs and operator marks with frame ids"
    )
    lines.append("  manifest.json          frame counts, drops, checksums, complete flag")
    lines.append("  visible.mp4/.json      visible camera (H.264) with host-clock timing")
    lines.append("  exports/roi_series.csv every ROI above on every frame, in °C")
    lines.append("  exports/roi_plot.png   the same series drawn against time with the marks")
    lines.append("  exports/thermal_preview.mp4  colorised viewing copy (not radiometric)")
    lines.append("  preview.png, keyframes.png   thumbnails")
    lines.append("")
    lines.append("Load in Python: zarr.open_group('thermal.zarr')['counts'] then apply the rule.")
    return "\n".join(lines) + "\n"


def _nice_ticks(lo: float, hi: float, n: int = 6) -> list[float]:
    if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
        return [lo]
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(s * mag for s in (1, 2, 5, 10) if s * mag >= raw)
    first = math.ceil(lo / step) * step
    return [first + i * step for i in range(int((hi - first) / step) + 1)]


NUC_MIN_REPEATS = 10
"""Frozen runs at least this long are marked as a NUC (mirrors lib/events.ts)."""


def plot_marks(reader: ExperimentReader) -> list[tuple[int, str]]:
    """(frame_id, label) for operator marks and NUC-length frozen runs, in event order."""
    out: list[tuple[int, str]] = []
    for e in reader.events:
        if e.get("type") == "annotation" and e.get("frame_id") is not None:
            out.append((int(e["frame_id"]), str(e.get("name", ""))))
        elif e.get("type") == "frozen_frames" and int(e.get("repeats", 0)) >= NUC_MIN_REPEATS:
            out.append((int(e["first_frame_id"]), f"NUC ({int(e['repeats'])} fr)"))
    return out


def roi_plot_png(reader: ExperimentReader, rois: list[dict[str, Any]]) -> bytes:
    """Traces of every ROI (value, or mean with min–max band) vs time, with operator marks."""
    series = roi_series(reader, rois)
    t = np.asarray(series["t_s"], dtype=float)
    font = ImageFont.load_default(size=26)
    img = Image.new("RGB", (PLOT_W, PLOT_H), (16, 17, 20))
    d = ImageDraw.Draw(img, "RGBA")
    x0, x1 = MARGIN_L, PLOT_W - MARGIN_R
    y0, y1 = MARGIN_T, PLOT_H - MARGIN_B
    traces: list[tuple[dict[str, Any], np.ndarray, np.ndarray | None, np.ndarray | None]] = []
    lo, hi = math.inf, -math.inf
    for r in rois:
        s = series["series"].get(str(r["id"]))  # keyed by ROI id as a string
        if s is None:
            continue
        main = np.asarray(
            [np.nan if v is None else v for v in (s.get("value") or s.get("mean") or [])], float
        )
        mn = (
            np.asarray([np.nan if v is None else v for v in s["min"]], float)
            if "min" in s
            else None
        )
        mx = (
            np.asarray([np.nan if v is None else v for v in s["max"]], float)
            if "max" in s
            else None
        )
        for a in (main, mn, mx):
            if a is not None and np.isfinite(a).any():
                lo, hi = min(lo, float(np.nanmin(a))), max(hi, float(np.nanmax(a)))
        traces.append((r, main, mn, mx))
    if not math.isfinite(lo):
        lo, hi = 0.0, 1.0
    if hi - lo < 1e-6:
        lo, hi = lo - 0.5, hi + 0.5
    pad = (hi - lo) * 0.05
    lo, hi = lo - pad, hi + pad
    tmax = float(t[-1]) if t.size and t[-1] > 0 else 1.0

    def px(tt: float) -> float:
        return x0 + (x1 - x0) * tt / tmax

    def py(v: float) -> float:
        return y1 - (y1 - y0) * (v - lo) / (hi - lo)

    for v in _nice_ticks(lo, hi):
        y = py(v)
        d.line([(x0, y), (x1, y)], fill=(255, 255, 255, 28))
        d.text((x0 - 16, y), f"{v:g}", fill=(200, 200, 200), font=font, anchor="rm")
    for tt in _nice_ticks(0, tmax, 8):
        x = px(tt)
        d.line([(x, y0), (x, y1)], fill=(255, 255, 255, 18))
        d.text((x, y1 + 12), f"{tt:g}", fill=(200, 200, 200), font=font, anchor="mt")
    d.rectangle([x0, y0, x1, y1], outline=(120, 120, 120))
    d.text((x0, y1 + 48), "time (s)", fill=(200, 200, 200), font=font)
    units = "°C" if (reader.ir_format or "").startswith("TemperatureLinear") else "counts"
    d.text((12, y0 - 44), units, fill=(200, 200, 200), font=font)
    for frame_id, label in plot_marks(reader):
        idx = np.searchsorted(np.asarray(series["frame_id"]), frame_id)
        if idx >= t.size:
            continue
        x = px(float(t[idx]))
        nuc = label.startswith("NUC")
        d.line(
            [(x, y0), (x, y1)], fill=(255, 200, 80, 150) if nuc else (255, 255, 255, 120), width=1
        )
        d.text((x + 6, y0 + 4), label, fill=(255, 210, 120) if nuc else (230, 230, 230), font=font)
    for i, (r, main, mn, mx) in enumerate(traces):
        col = r.get("color") or DEFAULT_COLORS[i % len(DEFAULT_COLORS)]
        rgb = tuple(int(col.lstrip("#")[j : j + 2], 16) for j in (0, 2, 4))
        if mn is not None and mx is not None:
            poly = [
                (px(float(t[k])), py(float(mn[k]))) for k in range(t.size) if np.isfinite(mn[k])
            ]
            poly += [
                (px(float(t[k])), py(float(mx[k])))
                for k in range(t.size - 1, -1, -1)
                if np.isfinite(mx[k])
            ]
            if len(poly) > 2:
                d.polygon(poly, fill=(*rgb, 50))
        pts = [(px(float(t[k])), py(float(main[k]))) for k in range(t.size) if np.isfinite(main[k])]
        if len(pts) > 1:
            d.line(pts, fill=(*rgb, 255), width=4)
        elif pts:
            d.ellipse(
                [pts[0][0] - 2, pts[0][1] - 2, pts[0][0] + 2, pts[0][1] + 2], fill=(*rgb, 255)
            )
        label = r.get("name") or f"{r['kind']} {r['id']}"
        lx = x0 + 20 + i * 320
        d.rectangle([lx, 16, lx + 24, 40], fill=(*rgb, 255))
        d.text((lx + 36, 14), label[:20], fill=(230, 230, 230), font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def write_run_summary(reader: ExperimentReader) -> dict[str, str | None]:
    """Write README.txt beside the store and exports/roi_plot.png when ROIs were stored."""
    readme = reader.path / "README.txt"
    readme.write_text(readme_text(reader), encoding="utf-8")
    plot: Path | None = None
    rois = reader.metadata.get("rois") or []
    if rois and reader.n_frames:
        out_dir = reader.path / "exports"
        out_dir.mkdir(exist_ok=True)
        plot = out_dir / "roi_plot.png"
        plot.write_bytes(roi_plot_png(reader, rois))
    return {"readme": str(readme), "roi_plot": str(plot) if plot else None}


__all__ = ["plot_marks", "readme_text", "roi_plot_png", "write_run_summary"]
