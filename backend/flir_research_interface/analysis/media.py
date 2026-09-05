"""Media export: render a chosen time window of a run to MP4 or GIF with optional overlays.

Builds on the thermal-video frame compositor (palette + color bar + elapsed time + ROIs) and adds
a title caption, a whole-frame min/max/mean readout, and — for GIF — a two-pass palette for clean
colors with a frame-count guard. See the media-export design spec under docs/superpowers/specs/.
"""

from __future__ import annotations

import logging
import math
import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from flir_research_interface.analysis.thermal_video import (
    FFMPEG_CANDIDATES,
    _encode_tmp,
    _finalize_encode,
    encode_command,
    label_font,
    load_range,
    run_range,
    save_range,
    thermal_frame_rgb,
)
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.radiometry.overrange import over_range_mask
from flir_research_interface.radiometry.temperature_linear import IRFormat, counts_to_celsius
from flir_research_interface.visible.rtsp import find_ffprobe

logger = logging.getLogger(__name__)

MAX_GIF_FRAMES = 300  # size guard: subsample so a GIF cannot balloon
CLIPS_DIR = "clips"

# A finished run's display range is fixed, but robust run_range scans every frame (slow on long
# runs). Cache it three ways so the scan is paid at most once ever: an in-process dict, and a
# persisted exports/range.json that survives operator restarts.
_RANGE_CACHE: dict[str, tuple[float, float, str]] = {}


def _cached_range(
    reader: ExperimentReader,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[float, float, str]:
    """Display (vmin, vmax, units): in-memory cache → persisted range.json → scan (once), persist.

    ``on_progress(done, total)`` is forwarded to the whole-run scan only when a scan is actually
    needed, so a caller can show a real progress bar for the one slow path.
    """
    key = str(reader.path)
    cached = _RANGE_CACHE.get(key)
    if cached is not None:
        return cached
    doc = load_range(reader)
    if doc is not None:
        rng = (float(doc["vmin"]), float(doc["vmax"]), str(doc["units"]))
        _RANGE_CACHE[key] = rng
        return rng
    lo, hi, units = run_range(reader, robust=True, on_progress=on_progress)
    save_range(reader, lo, hi, units)
    _RANGE_CACHE[key] = (lo, hi, units)
    return _RANGE_CACHE[key]


@dataclass(frozen=True)
class MediaOptions:
    start: int = 0
    stop: int = 0  # exclusive; 0 means "to the end"
    step: int = 1
    scale: int = 2
    speed: float = 1.0  # output plays `speed`× real time
    fps: float | None = None  # explicit output fps; otherwise source fps × speed
    fmt: str = "mp4"  # "mp4" | "gif"
    with_rois: bool = True
    frame_stats: bool = False
    timestamp: bool = True
    colorbar: bool = True
    title: str | None = None
    plot_roi: int | None = None  # legacy single-ROI live plot (kept for compatibility)
    plot_rois: tuple[int, ...] = ()  # legacy: ROIs drawn on the strip (× plot_stats, all the same)
    plot_stat: str = "mean"  # legacy single stat (kept for compatibility)
    plot_stats: tuple[str, ...] = ()  # legacy: stats applied to every plot_roi
    plot_series: tuple[tuple[int, str], ...] = ()  # per-ROI lines: (roi_id, stat) pairs
    overlay_rois: tuple[int, ...] = ()  # which ROI boxes to draw on the frame ((): all)
    visible_opacity: float = 0.0  # blend the recorded visible camera over the frame (0 = off)
    palette: str = "inferno"  # color palette for the thermal image + bar


def _slug(text: str) -> str:
    keep = "".join(c if c.isalnum() or c in "-_ " else "" for c in text).strip().replace(" ", "_")
    return keep[:48] or "clip"


_MAX_PLOT_PTS = 1200  # cap the drawn samples; the strip is only ~1200px wide anyway


def _plot_ids(opts: MediaOptions) -> list[int]:
    """The ROI ids to draw, from ``plot_rois`` (preferred) or the legacy ``plot_roi``."""
    if opts.plot_rois:
        return list(dict.fromkeys(opts.plot_rois))  # de-dupe, keep order
    return [opts.plot_roi] if opts.plot_roi is not None else []


def _plot_stats(opts: MediaOptions) -> list[str]:
    """The stats to draw per area ROI, from ``plot_stats`` or the legacy single ``plot_stat``."""
    stats = [s for s in (opts.plot_stats or (opts.plot_stat,)) if s in ("mean", "min", "max")]
    return list(dict.fromkeys(stats)) or ["mean"]


def _plot_pairs(opts: MediaOptions) -> list[tuple[int, str]]:
    """The (roi_id, stat) lines to draw. ``plot_series`` is per-ROI; the legacy fields apply the
    same stats to every selected ROI."""
    if opts.plot_series:
        return [(int(r), s) for r, s in opts.plot_series]
    ids = _plot_ids(opts)
    if not ids:
        return []
    stats = _plot_stats(opts)
    return [(rid, s) for rid in ids for s in stats]


def _overlay_rois(reader: ExperimentReader, opts: MediaOptions) -> list[dict[str, Any]]:
    """The ROI boxes to draw on the frame. ``overlay_rois`` limits them; empty means all.

    Each ROI gets its overlay palette color resolved from its *original* index, so filtering the
    list never shifts a ROI's color (and the box matches its plot line).
    """
    if not opts.with_rois:
        return []
    from flir_research_interface.analysis.annotate import DEFAULT_COLORS

    keep = set(opts.overlay_rois) if opts.overlay_rois else None
    out: list[dict[str, Any]] = []
    for i, r in enumerate(reader.metadata.get("rois") or []):
        if keep is not None and r.get("id") not in keep:
            continue
        rr = dict(r)
        rr["color"] = r.get("color") or DEFAULT_COLORS[i % len(DEFAULT_COLORS)]
        out.append(rr)
    return out



def _read_series_csv(reader: ExperimentReader) -> dict[str, Any] | None:
    """Parse a precomputed ``exports/roi_series.csv`` (fast path: no per-frame recompute).

    Columns are ``<Kind><id>_<stat>`` (e.g. ``C7_mean``, ``R36_max``, ``S43_value``); we key them
    by the numeric id so the ROI's kind letter does not matter. Returns None when absent/unusable.
    """
    import csv

    path = reader.path / "exports" / "roi_series.csv"
    if not path.is_file():
        return None
    try:
        with path.open(newline="") as f:
            reader_csv = csv.reader(row for row in f if not row.startswith("#"))
            header = next(reader_csv, None)
            if not header:
                return None
            cols: dict[tuple[int, str], int] = {}
            t_col = header.index("t_s") if "t_s" in header else None
            for j, name in enumerate(header):
                m = re.match(r"^[A-Za-z]+(\d+)_(mean|min|max|value)$", name)
                if m:
                    cols[(int(m.group(1)), m.group(2))] = j
            ts: list[float] = []
            data: dict[tuple[int, str], list[float]] = {k: [] for k in cols}
            for row in reader_csv:
                if not row:
                    continue
                ts.append(float(row[t_col]) if t_col is not None else float(len(ts)))
                for k, j in cols.items():
                    try:
                        data[k].append(float(row[j]))
                    except (ValueError, IndexError):
                        data[k].append(float("nan"))
        return {"t_s": ts, "data": data}
    except (OSError, ValueError, StopIteration):
        return None


def _downsample(t: list[float], v: list[float]) -> tuple[list[float], list[float]]:
    if len(t) <= _MAX_PLOT_PTS:
        return t, v
    stride = math.ceil(len(t) / _MAX_PLOT_PTS)
    return t[::stride], v[::stride]


def _plot_traces(reader: ExperimentReader, opts: MediaOptions) -> list[dict[str, Any]]:
    """One trace per (chosen ROI × chosen stat) over the window, for the live-plot strip.

    Reads the precomputed ``exports/roi_series.csv`` when present (instant); otherwise falls back
    to computing the series from the store. Colors match the on-frame ROI overlay, which assigns
    ``DEFAULT_COLORS`` by list order when a ROI has no explicit color.
    """
    pairs = _plot_pairs(opts)
    if not pairs:
        return []
    from flir_research_interface.analysis.annotate import DEFAULT_COLORS, _rgb

    stored = reader.metadata.get("rois") or []
    idx_of = {r["id"]: i for i, r in enumerate(stored)}
    roi_of = {r["id"]: r for r in stored}
    lo, hi = opts.start, (opts.stop or reader.n_frames)
    csv_series = _read_series_csv(reader)
    series_cache: dict[int, tuple[list[float], dict[str, list[float]]] | None] = {}
    out: list[dict[str, Any]] = []
    for rid, stat in pairs:
        roi = roi_of.get(rid)
        if roi is None:
            continue
        is_spot = roi.get("kind") == "spot"
        key = "value" if is_spot else stat
        if rid not in series_cache:  # read each ROI's series once, even for several stats
            series_cache[rid] = _roi_values(reader, roi, csv_series)
        series = series_cache[rid]
        if series is None:
            continue
        t_all, by_stat = series
        arr = by_stat.get(key) or by_stat.get("mean") or by_stat.get("value")
        if not arr:
            continue
        t_win = [t for k, t in enumerate(t_all) if lo <= k < hi]
        v_win = [arr[k] for k in range(len(arr)) if lo <= k < hi]
        t_ds, v_ds = _downsample(t_win, v_win)
        base = _rgb(roi.get("color") or DEFAULT_COLORS[idx_of[rid] % len(DEFAULT_COLORS)])
        name = str(roi.get("name") or f"ROI {rid}")
        label = name if is_spot else f"{name} · {key}"
        # keep the ROI's own color for every stat; the stat is shown by line style + marker.
        out.append({"v": v_ds, "t": t_ds, "label": label, "color": base, "stat": key})
    return out


def _roi_values(
    reader: ExperimentReader, roi: dict[str, Any], csv_series: dict[str, Any] | None
) -> tuple[list[float], dict[str, list[float]]] | None:
    """(t_s, {stat: values}) for one ROI — from the CSV if it has this ROI, else recomputed."""
    rid = roi["id"]
    if csv_series is not None:
        keys = {s for (cid, s) in csv_series["data"] if cid == rid}
        if keys:
            return csv_series["t_s"], {s: csv_series["data"][(rid, s)] for s in keys}
    from flir_research_interface.analysis.series import roi_series

    res = roi_series(reader, [roi])
    ser = res["series"].get(str(rid))
    if not ser:
        return None
    return [float(x) for x in res["t_s"]], {k: [float(x) for x in v] for k, v in ser.items()}


_PANEL_H = 120  # height of the live-plot strip appended below the frame
_AXIS = (150, 150, 156)
_GRID = (60, 60, 66)
_MUTE = (180, 180, 186)


def _nice_ticks(lo: float, hi: float, target: int = 4) -> list[float]:
    """A short list of round tick values spanning [lo, hi] (1/2/5 × 10^k spacing)."""
    span = hi - lo
    if span <= 0:
        return [lo]
    raw = span / max(1, target)
    mag = 10.0 ** math.floor(math.log10(raw))
    step = next((m * mag for m in (1, 2, 5, 10) if m * mag >= raw), 10 * mag)
    start = math.ceil(lo / step) * step
    ticks, t = [], start
    while t <= hi + step * 1e-6:
        ticks.append(round(t, 6))
        t += step
    return ticks or [lo, hi]


# Each stat gets a distinct line style + marker so several stats of one ROI (same color) read
# apart: mean = solid + circle, max = dashed + up-triangle, min = dotted + down-triangle.
_STAT_STYLE = {
    "mean": {"dash": None, "marker": "o"},
    "max": {"dash": (9, 5), "marker": "^"},
    "min": {"dash": (2, 4), "marker": "v"},
    "value": {"dash": None, "marker": "o"},
}


def _dashed(d: ImageDraw.ImageDraw, pts: list[tuple[float, float]], col: tuple[int, ...],
            width: int, dash: tuple[int, int] | None) -> None:
    """Polyline, solid when ``dash`` is None, else on/off dashes of (on, off) px along the path."""
    if len(pts) < 2:
        return
    if dash is None:
        d.line(pts, fill=col, width=width)
        return
    on, off = dash
    draw_on, rem = True, on
    for (x1, y1), (x2, y2) in zip(pts, pts[1:], strict=False):
        seg = math.hypot(x2 - x1, y2 - y1)
        done = 0.0
        while done < seg:
            step = min(rem, seg - done)
            f0, f1 = done / seg, (done + step) / seg
            if draw_on:
                d.line((x1 + (x2 - x1) * f0, y1 + (y2 - y1) * f0,
                        x1 + (x2 - x1) * f1, y1 + (y2 - y1) * f1), fill=col, width=width)
            done += step
            rem -= step
            if rem <= 1e-6:
                draw_on = not draw_on
                rem = on if draw_on else off


def _marker(d: ImageDraw.ImageDraw, x: float, y: float, shape: str, col: tuple[int, ...],
            r: float, scrim: tuple[int, int, int] = (12, 12, 14)) -> None:
    if shape == "^":
        pts = [(x, y - r), (x + r, y + r), (x - r, y + r)]
    elif shape == "v":
        pts = [(x, y + r), (x + r, y - r), (x - r, y - r)]
    else:
        d.ellipse((x - r, y - r, x + r, y + r), fill=col, outline=scrim)
        return
    d.polygon(pts, fill=col, outline=scrim)


def _draw_panel(d: ImageDraw.ImageDraw, traces: list[dict[str, Any]], cur_t: float, x0: int,
                y0: int, w: int, h: int, font: ImageFont.FreeTypeFont) -> None:
    """A full-width, multi-line plot over time, drawn up to ``cur_t`` (seconds), with °C y-ticks,
    a wrapping legend, and a distinct line style + marker per stat."""
    finite = [x for tr in traces for x in tr["v"] if x == x]
    all_t = [t for tr in traces for t in tr["t"]]
    if not finite or not all_t:
        return
    lo, hi = min(finite), max(finite)
    if hi - lo < 1e-6:
        lo, hi = lo - 0.5, hi + 0.5
    t0, t1 = min(all_t), max(all_t)
    pad = max(4, font.size // 3)
    yticks = _nice_ticks(lo, hi)
    gutter = int(max(d.textlength(f"{t:.0f}", font=font) for t in yticks)) + 8
    line_h = font.size + 5

    # --- wrapping legend across the top: swatch + "name · stat  value°" per entry -------------
    def cur_val(tr: dict[str, Any]) -> float | None:
        v, ts = tr["v"], tr["t"]
        return next((v[k] for k in range(len(v) - 1, -1, -1)
                     if v[k] == v[k] and ts[k] <= cur_t + 1e-6), None)
    entries = []
    for tr in traces:
        c = cur_val(tr)
        txt = f"{tr['label']}  {c:.1f}°" if c is not None else str(tr["label"])
        entries.append((tr, txt, 20 + int(d.textlength(txt, font=font)) + 14))
    rows, row, rw = [], [], 0
    for e in entries:
        if row and rw + e[2] > w - 4:
            rows.append(row)
            row, rw = [], 0
        row.append(e)
        rw += e[2]
    if row:
        rows.append(row)
    legend_h = len(rows) * line_h + 4
    for ri, r in enumerate(rows):
        lx = x0 + 2
        ly = y0 + 2 + ri * line_h
        for tr, txt, ewidth in r:
            col = tuple(tr["color"])
            st = _STAT_STYLE.get(tr.get("stat", "mean"), _STAT_STYLE["mean"])
            d.line((lx, ly + line_h / 2, lx + 15, ly + line_h / 2), fill=col, width=2)  # style key
            _marker(d, lx + 7.5, ly + line_h / 2, st["marker"], col, max(2.5, font.size / 4))
            d.text((lx + 20, ly), txt, fill=(235, 235, 240), font=font)
            lx += ewidth

    ax0, ay0 = x0 + gutter, y0 + legend_h + pad
    aw = w - gutter - pad - 6
    ah = h - legend_h - pad - (font.size + 6)  # room for x-tick labels at the bottom

    def px(t: float) -> float:
        return ax0 + aw * (t - t0) / max(1e-6, t1 - t0)

    def py(val: float) -> float:
        return ay0 + ah - ah * (val - lo) / (hi - lo)

    for tv in yticks:  # y grid + tick marks + °C unit
        gy = py(tv)
        d.line((ax0, gy, ax0 + aw, gy), fill=_GRID)
        d.line((ax0 - 4, gy, ax0, gy), fill=_AXIS)
        d.text((x0 + 2, gy - font.size / 2), f"{tv:.0f}", fill=_MUTE, font=font)
    d.rectangle((ax0, ay0, ax0 + aw, ay0 + ah), outline=_AXIS)
    d.text((x0 + 2, ay0 - font.size - 1), "°C", fill=_MUTE, font=font)

    if t1 - t0 > 1e-6:  # x tick marks along the time axis (denser)
        n_x = max(6, min(12, int(aw / 90)))
        for tt in _nice_ticks(t0, t1, n_x):
            gx = px(tt)
            d.line((gx, ay0, gx, ay0 + ah), fill=_GRID)  # vertical gridline
            d.line((gx, ay0 + ah, gx, ay0 + ah + 4), fill=_AXIS)
            lbl = f"{tt:.0f}s"
            d.text((gx - d.textlength(lbl, font=font) / 2, ay0 + ah + 4), lbl,
                   fill=_MUTE, font=font)

    for tr in traces:  # one line per (ROI, stat): ROI color, stat = style + periodic marker
        col = tuple(tr["color"])
        st = _STAT_STYLE.get(tr.get("stat", "mean"), _STAT_STYLE["mean"])
        ts, v = tr["t"], tr["v"]
        drawn = [(px(ts[k]), py(v[k])) for k in range(len(v))
                 if v[k] == v[k] and ts[k] <= cur_t + 1e-6]
        _dashed(d, drawn, col, 2, st["dash"])
        step = max(1, len(drawn) // max(1, int(aw / 60)))  # a few markers, not a clog
        for k in range(0, len(drawn), step):
            _marker(d, drawn[k][0], drawn[k][1], st["marker"], col, max(2.5, font.size / 4))
        if drawn:
            _marker(d, drawn[-1][0], drawn[-1][1], st["marker"], col, max(3.0, font.size / 3))
    hx = px(max(t0, min(t1, cur_t)))  # playhead rule shared by all lines
    d.line((hx, ay0, hx, ay0 + ah), fill=(120, 120, 128))


def _celsius(reader: ExperimentReader, idx: int) -> tuple[np.ndarray, np.ndarray]:
    block = reader.counts_block(idx, idx + 1)[0]
    fmt = reader.metadata.get("conversion", {}).get("ir_format") or reader.ir_format
    return counts_to_celsius(block, IRFormat(fmt)), block


def render_clip(
    reader: ExperimentReader,
    opts: MediaOptions,
    *,
    ffmpeg: str | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Render the window ``[start, stop)`` (every ``step``) to MP4/GIF. Returns file info."""
    n = reader.n_frames
    stop = opts.stop or n
    if opts.step < 1 or not (0 <= opts.start < stop <= n):
        raise ValueError(f"need 0 <= start < stop <= {n} and step >= 1")
    if opts.fmt not in ("mp4", "gif"):
        raise ValueError("fmt must be 'mp4' or 'gif'")
    ffmpeg = ffmpeg or find_ffprobe(FFMPEG_CANDIDATES)
    if ffmpeg is None:
        raise RuntimeError("ffmpeg not found")

    indices = list(range(opts.start, stop, opts.step))
    guard_note = None
    if opts.fmt == "gif" and len(indices) > MAX_GIF_FRAMES:
        stride = math.ceil(len(indices) / MAX_GIF_FRAMES)
        indices = indices[::stride]
        guard_note = f"subsampled to {len(indices)} frames to keep the GIF small"

    vmin, vmax, _units = _cached_range(reader)
    _, h0, w0 = reader.counts_block(0, 1).shape
    scale = max(1, opts.scale)
    rois = _overlay_rois(reader, opts)
    traces = _plot_traces(reader, opts)
    vsrc = _visible_source(reader, opts, ffmpeg,
                           float(reader.t_s(indices[0])), float(reader.t_s(indices[-1])),
                           w0 * scale, h0 * scale)
    try:
        # size the first frame to fix the encoder geometry
        first = _compose(reader, indices[0], vmin, vmax, scale, rois, opts, traces,
                         float(reader.t_s(indices[0])), vsrc)
        height, width = first.shape[0], first.shape[1]
        if width % 2 or height % 2:
            width += width % 2
            height += height % 2

        src_fps = _fps(reader)
        out_fps = opts.fps or max(1.0, src_fps * opts.speed)
        if opts.fmt == "gif":
            out_fps = min(out_fps, 20.0)

        out_dir = reader.path / "exports" / CLIPS_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = _slug(opts.title or f"clip_{opts.start}-{stop}")
        total = len(indices)

        def _frames() -> np.ndarray:
            for k, idx in enumerate(indices):
                rgb = (first if k == 0 else
                       _compose(reader, idx, vmin, vmax, scale, rois, opts, traces,
                                float(reader.t_s(idx)), vsrc))
                if rgb.shape[0] != height or rgb.shape[1] != width:
                    pad = np.zeros((height, width, 3), dtype=np.uint8)
                    pad[: rgb.shape[0], : rgb.shape[1]] = rgb
                    rgb = pad
                yield k, rgb

        if opts.fmt == "mp4":
            out = out_dir / f"{stem}.mp4"
            info = _encode_mp4(ffmpeg, width, height, out_fps, out, _frames(), total, on_progress)
        else:
            out = out_dir / f"{stem}.gif"
            info = _encode_gif(ffmpeg, width, height, out_fps, out, _frames(), total, on_progress)
    finally:
        if vsrc is not None:
            vsrc.close()
    info.update({"path": str(out), "name": out.name, "frames": total, "fps": out_fps,
                 "width": width, "height": height, "bytes": out.stat().st_size, "note": guard_note})
    logger.info("media clip written: %s", info)
    return info


def _visible_source(reader: ExperimentReader, opts: MediaOptions, ffmpeg: str,
                    t0: float, t1: float, out_w: int, out_h: int) -> Any:
    """A VisibleSource covering [t0, t1] when the visible overlay is requested, else None."""
    if opts.visible_opacity <= 0:
        return None
    from flir_research_interface.analysis.visible_overlay import VisibleSource
    return VisibleSource(reader, ffmpeg, t0, t1, out_w, out_h)


def _compose(reader: ExperimentReader, idx: int, vmin: float, vmax: float, scale: int,
             rois: list[dict[str, Any]], opts: MediaOptions,
             plot: list[dict[str, Any]] | None = None, cur_t: float = 0.0,
             visible: Any = None) -> np.ndarray:
    values, counts = _celsius(reader, idx)
    over = over_range_mask(counts)
    stats_vals = values if over is None else np.where(over, np.nan, values)
    bar = 24 if opts.colorbar else 0
    # A title paints a bar over the top-left, so let it own that corner: draw the timestamp just
    # below the bar instead of having thermal_frame_rgb bake it under the title.
    rgb = thermal_frame_rgb(values, vmin, vmax, reader.t_s(idx), bar_px=bar, scale=scale,
                            rois=rois if opts.with_rois else None, reader=reader,
                            show_time=opts.timestamp and not opts.title, palette=opts.palette)
    if over is not None:  # paint over-range pixels magenta, like the live display
        rgb = np.array(rgb, copy=True)  # thermal_frame_rgb may hand back a read-only view
        big = np.repeat(np.repeat(over, scale, axis=0), scale, axis=1)
        rgb[: big.shape[0], : big.shape[1]][big] = (255, 0, 255)
    if visible is not None and opts.visible_opacity > 0:  # blend the recorded visible camera
        from flir_research_interface.analysis.visible_overlay import blend_visible
        warped = visible.warped_at(cur_t)
        if warped is not None:
            bh, bw = values.shape[0] * scale, values.shape[1] * scale
            rgb = np.array(rgb, copy=True) if not rgb.flags.writeable else rgb
            rgb[:bh, :bw] = blend_visible(rgb[:bh, :bw], warped, opts.visible_opacity)
    pil = Image.fromarray(rgb).convert("RGB")
    d = ImageDraw.Draw(pil, "RGBA")
    font = label_font(max(11, min(18, rgb.shape[0] // 26)))
    if opts.frame_stats:
        lo, hi, mean = np.nanmin(stats_vals), np.nanmax(stats_vals), np.nanmean(stats_vals)
        txt = f"min {lo:.1f}  max {hi:.1f}  mean {mean:.1f} °C"
        d.text((4, rgb.shape[0] - 2 * font.size - 8), txt, fill=(255, 255, 255), font=font)
    if opts.title:
        bar_h = font.size + 8
        tw = d.textlength(opts.title, font=font)
        d.rectangle((0, 0, rgb.shape[1], bar_h), fill=(0, 0, 0))
        d.text(((rgb.shape[1] - tw) / 2, 3), opts.title, fill=(255, 255, 255), font=font)
        if opts.timestamp:  # timestamp moved just under the title bar so the bar can't cover it
            d.text((4, bar_h + 2), f"{reader.t_s(idx):.2f} s", fill=(255, 255, 255), font=font)
    if not plot:
        return np.asarray(pil, dtype=np.uint8)
    # append a full-width live-plot strip below the frame; it grows taller as the wrapping legend
    # needs more rows, so many ROI×stat lines stay readable (taller output, no overlay).
    pfont = label_font(max(11, min(18, (_PANEL_H * scale) // 8)))
    per_row = max(1, rgb.shape[1] // 210)
    legend_rows = max(1, math.ceil(len(plot) / per_row))
    panel = (_PANEL_H + (legend_rows - 1) * 22) * scale
    canvas = Image.new("RGB", (rgb.shape[1], rgb.shape[0] + panel), (14, 14, 16))
    canvas.paste(pil, (0, 0))
    dp = ImageDraw.Draw(canvas, "RGBA")
    _draw_panel(dp, plot, cur_t, 0, rgb.shape[0], rgb.shape[1], panel, pfont)
    return np.asarray(canvas, dtype=np.uint8)


def _fps(reader: ExperimentReader) -> float:
    try:
        t = reader.timeline()["t_s"]
        if len(t) > 1:
            dt = (t[-1] - t[0]) / (len(t) - 1)
            return 1.0 / dt if dt > 0 else 30.0
    except Exception:  # noqa: BLE001
        pass
    return 30.0


def _pump(proc: subprocess.Popen[bytes], frames: Any, total: int,
          on_progress: Callable[[int, int], None] | None) -> None:
    assert proc.stdin is not None
    try:
        for k, rgb in frames:
            proc.stdin.write(np.ascontiguousarray(rgb).tobytes())
            if on_progress is not None:
                on_progress(k + 1, total)
    except BrokenPipeError:
        pass


def _encode_mp4(  # type: ignore[no-untyped-def]
    ffmpeg, width, height, fps, out, frames, total, on_progress
) -> dict[str, Any]:
    tmp = _encode_tmp(".mp4")  # encode in the system temp dir, not the Dropbox-synced exports/
    proc = subprocess.Popen(encode_command(ffmpeg, width, height, fps, tmp),
                            stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    _pump(proc, frames, total, on_progress)
    _, err = proc.communicate(timeout=600)
    if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        tail = err.decode(errors="replace")[-400:]
        raise RuntimeError(f"ffmpeg failed (rc {proc.returncode}): {tail}")
    _finalize_encode(tmp, out)
    return {}


def _encode_gif(  # type: ignore[no-untyped-def]
    ffmpeg, width, height, fps, out, frames, total, on_progress
) -> dict[str, Any]:
    # write raw frames once, then two-pass palettegen/paletteuse for clean colors
    with tempfile.TemporaryDirectory() as td:
        raw = Path(td) / "frames.rgb"
        with raw.open("wb") as f:
            for k, rgb in frames:
                f.write(np.ascontiguousarray(rgb).tobytes())
                if on_progress is not None:
                    on_progress(k + 1, total)
        pal = Path(td) / "pal.png"
        base = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
                "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", f"{fps:g}", "-i", str(raw)]
        subprocess.run([*base, "-vf", "palettegen=stats_mode=diff", str(pal)], check=True,
                       capture_output=True, timeout=600)
        tmp = Path(td) / "out.gif"  # build the GIF in the temp dir, then move it into exports/
        r = subprocess.run([*base, "-i", str(pal), "-lavfi",
                            "paletteuse=dither=bayer:bayer_scale=3", str(tmp)],
                           capture_output=True, timeout=600)
        if r.returncode != 0 or not tmp.is_file():
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"gif encode failed: {r.stderr.decode(errors='replace')[-400:]}")
        _finalize_encode(tmp, out)
    return {}


def compose_preview(reader: ExperimentReader, opts: MediaOptions, index: int) -> bytes:
    """One composed frame (same overlays as the export) as PNG bytes for the live preview."""
    if not (0 <= index < reader.n_frames):
        raise ValueError(f"index out of range 0..{reader.n_frames - 1}")
    vmin, vmax, _ = _cached_range(reader)
    scale = max(1, opts.scale)
    rois = _overlay_rois(reader, opts)
    traces = _plot_traces(reader, opts)  # covers the window; grows to the current time as you scrub
    t = float(reader.t_s(index))
    _, h0, w0 = reader.counts_block(0, 1).shape
    ffmpeg = find_ffprobe(FFMPEG_CANDIDATES)
    vsrc = (_visible_source(reader, opts, ffmpeg, t, t, w0 * scale, h0 * scale)
            if ffmpeg else None)
    try:
        rgb = _compose(reader, index, vmin, vmax, scale, rois, opts, traces, t, vsrc)
    finally:
        if vsrc is not None:
            vsrc.close()
    from io import BytesIO

    buf = BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG")
    return buf.getvalue()


__all__ = ["MediaOptions", "render_clip", "compose_preview", "MAX_GIF_FRAMES"]
