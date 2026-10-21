"""Timeline plot of the visible sample analysis: ``exports/visible_sample_plot.png``.

Four panels share the thermal time axis (seconds since thermal frame 0): RF forward power, the
sample ROI's max and mean temperature, the sample's dark-pixel count, and the brightening of the
sample in the visible video. Each flash event is a vertical line at its peak in every panel,
labelled with the peak brightening. Drawn with Pillow on the canvas, colours and font of
``roi_plot_png`` (``analysis/run_summary.py``); the plot is derived and regenerable.

Nothing is drawn for a value that is not there: a gap in the video, a keyframe (whose brightening
is the encoder's refresh) or a missing RF trace leaves a break or an empty panel with a note.
"""

from __future__ import annotations

import io
import math
from collections.abc import Sequence
from typing import Any, NamedTuple

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw, ImageFont

from flir_research_interface.analysis.control_series import control_series_from_rows
from flir_research_interface.analysis.run_summary import (
    DEFAULT_COLORS,
    FRAME_RGB,
    GRID_H_RGBA,
    GRID_V_RGBA,
    LABEL_RGB,
    MARGIN_B,
    MARGIN_L,
    MARGIN_R,
    MARGIN_T,
    PLOT_BG,
    PLOT_FONT_SIZE,
    PLOT_H,
    PLOT_W,
    TICK_RGB,
    _nice_ticks,
)
from flir_research_interface.analysis.series import roi_series
from flir_research_interface.playback.reader import ExperimentReader

Floats = NDArray[np.float64]
Colour = tuple[int, ...]  # RGB or RGBA


def _rgb(hex_colour: str) -> tuple[int, int, int]:
    return (int(hex_colour[1:3], 16), int(hex_colour[3:5], 16), int(hex_colour[5:7], 16))


RF_RGB = _rgb(DEFAULT_COLORS[0])
MEAN_RGB = _rgb(DEFAULT_COLORS[1])
EVENT_RGB = _rgb(DEFAULT_COLORS[2])
BRIGHT_RGB = _rgb(DEFAULT_COLORS[3])
MAX_RGB = _rgb(DEFAULT_COLORS[4])
DARK_RGB = _rgb(DEFAULT_COLORS[5])
CEILING_RGB = _rgb(DEFAULT_COLORS[6])

ROLLING_WINDOW = 31  # frames, for the median over sample_dark_px
GAP_BREAK_S = 2.0  # a line is not drawn across a stretch with no analysed frame this long
N_PANELS = 4
PANEL_GAP = 56  # between panels: the next panel's legend sits here
LEGEND_ABOVE = 44  # a legend chip starts this far above its panel
RAW_ALPHA = 90  # the raw dark-pixel trace is dim behind its rolling median


# -- the numbers behind the lines ---------------------------------------------------------------


class RowArrays(NamedTuple):
    """The runner's per-frame rows as arrays; ``brightening`` is NaN where it is not a value."""

    t: Floats
    segment: NDArray[np.int64]
    dark_px: Floats
    brightening: Floats


def row_arrays(rows: Sequence[dict[str, Any]]) -> RowArrays:
    """Arrays of the rows that ``visible_sample_run._measure`` makes. A keyframe's brightening is
    the encoder's refresh, not the scene, so it is left out here whatever the row carries."""
    return RowArrays(
        t=np.array([r["t_s"] for r in rows], dtype=float),
        segment=np.array([r["segment"] for r in rows], dtype=np.int64),
        dark_px=np.array([r["sample_dark_px"] for r in rows], dtype=float),
        brightening=np.array(
            [
                np.nan if r["keyframe"] or r["brightening"] is None else r["brightening"]
                for r in rows
            ],
            dtype=float,
        ),
    )


def rolling_median(values: Floats, window: int = ROLLING_WINDOW) -> Floats:
    """The centred rolling median of finite ``values``; the window shrinks at the ends, so no
    value is invented beyond them."""
    half = window // 2
    return np.array(
        [np.median(values[max(0, i - half) : i + half + 1]) for i in range(values.size)],
        dtype=float,
    )


def median_by_run(values: Floats, runs: list[slice], window: int = ROLLING_WINDOW) -> Floats:
    """``rolling_median`` taken within each run, so no window reaches across a gap in the video;
    NaN for a row that is in no run."""
    out = np.full(values.size, np.nan)
    for run in runs:
        out[run] = rolling_median(values[run], window)
    return out


def line_runs(t: Floats, segment: NDArray[np.int64], gap_s: float = GAP_BREAK_S) -> list[slice]:
    """Index ranges of rows that one line may join: a new run starts where the segment changes or
    where more than ``gap_s`` passes with no analysed frame (the camera link was down)."""
    if t.size == 0:
        return []
    cuts = np.flatnonzero((np.diff(segment) != 0) | (np.diff(t) > gap_s)) + 1
    edges = [0, *cuts.tolist(), t.size]
    return [slice(a, b) for a, b in zip(edges[:-1], edges[1:], strict=True)]


def unit_label(units: str) -> str:
    """The axis unit for ``roi_series``'s ``units``: only ``"celsius"`` is a temperature."""
    return "°C" if units == "celsius" else "counts"


def panel_boxes() -> list[tuple[int, int]]:
    """``(top, bottom)`` pixel rows of the four panels, top to bottom, between the margins of
    ``roi_plot_png`` with a gap for each panel's legend."""
    height = (PLOT_H - MARGIN_B - MARGIN_T - (N_PANELS - 1) * PANEL_GAP) // N_PANELS
    tops = [MARGIN_T + i * (height + PANEL_GAP) for i in range(N_PANELS)]
    return [(top, top + height) for top in tops]


def _y_range(*arrays: Floats, zero: bool = False) -> tuple[float, float]:
    """Axis limits around the finite values, 5 % padding (as ``roi_plot_png``); ``zero`` keeps 0
    in view. No finite value gives 0 to 1."""
    finite = np.concatenate([a[np.isfinite(a)] for a in arrays]) if arrays else np.zeros(0)
    if finite.size == 0:
        lo, hi = 0.0, 1.0
    else:
        lo, hi = float(finite.min()), float(finite.max())
        lo = min(lo, 0.0) if zero else lo
    if hi - lo < 1e-6:
        lo, hi = lo - 0.5, hi + 0.5
    pad = (hi - lo) * 0.05
    return lo - pad, hi + pad


def _floats(values: Sequence[float | None]) -> Floats:
    return np.array([np.nan if v is None else v for v in values], dtype=float)


# -- drawing ------------------------------------------------------------------------------------


class _Canvas:
    """The image and the time-to-pixel map the four panels share."""

    def __init__(self, tmax: float) -> None:
        self.img = Image.new("RGB", (PLOT_W, PLOT_H), PLOT_BG)
        self.d = ImageDraw.Draw(self.img, "RGBA")
        self.font = ImageFont.load_default(size=PLOT_FONT_SIZE)
        self.x0, self.x1, self.tmax = MARGIN_L, PLOT_W - MARGIN_R, tmax

    def px(self, t: float) -> float:
        return self.x0 + (self.x1 - self.x0) * t / self.tmax


class _Panel:
    """One panel: its box, value range, grid and axis numbers, legend and traces."""

    def __init__(
        self, canvas: _Canvas, box: tuple[int, int], limits: tuple[float, float], last: bool
    ) -> None:
        self.c = canvas
        self.top, self.bottom = box
        self.lo, self.hi = limits
        d, font = canvas.d, canvas.font
        for v in _nice_ticks(self.lo, self.hi, 3):
            d.line([(canvas.x0, self.py(v)), (canvas.x1, self.py(v))], fill=GRID_H_RGBA)
            d.text((canvas.x0 - 16, self.py(v)), f"{v:g}", fill=TICK_RGB, font=font, anchor="rm")
        for t in _nice_ticks(0, canvas.tmax, 8):
            x = canvas.px(t)
            d.line([(x, self.top), (x, self.bottom)], fill=GRID_V_RGBA)
            if last:  # the time axis is shared: numbers under the bottom panel only
                d.text((x, self.bottom + 12), f"{t:g}", fill=TICK_RGB, font=font, anchor="mt")
        d.rectangle([canvas.x0, self.top, canvas.x1, self.bottom], outline=FRAME_RGB)

    def py(self, v: float) -> float:
        return self.bottom - (self.bottom - self.top) * (v - self.lo) / (self.hi - self.lo)

    def legend(self, items: list[tuple[Colour | None, str]]) -> None:
        """Chips and names above the panel; a ``None`` colour is a name without a chip."""
        c, x = self.c, self.c.x0 + 20
        for colour, name in items:
            if colour is not None:
                top = self.top - LEGEND_ABOVE
                c.d.rectangle([x, top, x + 24, top + 24], fill=colour)
                x += 36
            c.d.text((x, self.top - LEGEND_ABOVE - 2), name, fill=LABEL_RGB, font=c.font)
            x += int(c.d.textlength(name, font=c.font)) + 40

    def note(self, text: str) -> None:
        mid = ((self.c.x0 + self.c.x1) / 2, (self.top + self.bottom) / 2)
        self.c.d.text(mid, text, fill=TICK_RGB, font=self.c.font, anchor="mm")

    def trace(self, t: Floats, v: Floats, runs: list[slice], colour: Colour, width: int) -> None:
        """A line per run, broken wherever ``v`` is not finite; a lone point is a dot."""
        d = self.c.d

        def flush(points: list[tuple[float, float]]) -> None:
            if len(points) > 1:
                d.line(points, fill=colour, width=width, joint="curve")
            elif points:
                x, y = points[0]
                d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=colour)

        for run in runs:
            points: list[tuple[float, float]] = []
            for k in range(run.start, run.stop):
                if math.isfinite(v[k]):
                    points.append((self.c.px(float(t[k])), self.py(float(v[k]))))
                else:
                    flush(points)
                    points = []
            flush(points)

    def dotted(self, value: float, colour: Colour) -> None:
        y = self.py(value)
        for x in range(int(self.c.x0), int(self.c.x1), 16):
            self.c.d.line([(x, y), (min(x + 8, self.c.x1), y)], fill=colour, width=3)

    def event_lines(self, events: list[dict[str, Any]]) -> None:
        for ev in events:
            x = self.c.px(float(ev["t_peak_s"]))
            self.c.d.line([(x, self.top), (x, self.bottom)], fill=EVENT_RGB, width=2)

    def event_labels(self, events: list[dict[str, Any]]) -> None:
        """The peak value beside each line, at the top; neighbours alternate between two rows."""
        c = self.c
        for i, ev in enumerate(events):
            text = f"{float(ev['peak_brightening']):.0f}"
            x, y = c.px(float(ev["t_peak_s"])), self.top + 4 + (i % 2) * (PLOT_FONT_SIZE + 4)
            if x + 6 + c.d.textlength(text, font=c.font) > c.x1:  # no room: put it left of the line
                c.d.text((x - 6, y), text, fill=EVENT_RGB, font=c.font, anchor="ra")
            else:
                c.d.text((x + 6, y), text, fill=EVENT_RGB, font=c.font)


def _sample_roi(reader: ExperimentReader, summary: dict[str, Any]) -> dict[str, Any]:
    """The full ROI the summary names (``roi_series`` needs its geometry, not just its id)."""
    wanted = (summary.get("sample_roi") or {}).get("id")
    for roi in reader.metadata.get("rois") or []:
        if roi.get("id") == wanted:
            return dict(roi)
    raise ValueError(f"sample ROI {wanted!r} is not among the run's ROIs")


def _reached_limit(reader: ExperimentReader, units: str, s_max: Floats) -> float | None:
    """The active measurement case's upper limit (C, stored with the recording) when the sample
    max reaches it; ``None`` otherwise. A limit in C says nothing about raw counts."""
    case = (reader.metadata.get("camera") or {}).get("active_case") or {}
    high = case.get("high_c")
    if units != "celsius" or not isinstance(high, int | float) or isinstance(high, bool):
        return None
    reached = bool(np.isfinite(s_max).any()) and float(np.nanmax(s_max)) >= high
    return float(high) if reached else None


def _draw_rf(panel: _Panel, t: Floats, forward: Floats) -> None:
    if not np.isfinite(forward).any():
        panel.legend([(None, "RF forward (W)")])
        panel.note("no RF forward power in this run's control samples")
        return
    panel.legend([(RF_RGB, "RF forward (W)")])
    panel.trace(t, forward, [slice(0, t.size)], RF_RGB, 4)


def _draw_temperature(
    panel: _Panel,
    t: Floats,
    s_max: Floats,
    s_mean: Floats,
    limit: float | None,
    name: str,
    unit: str,
) -> None:
    items: list[tuple[Colour | None, str]] = [(MAX_RGB, f"{name} max"), (MEAN_RGB, "mean")]
    if limit is not None:
        items.append((CEILING_RGB, f"case limit {limit:g} {unit}"))
    panel.legend(items)
    if not np.isfinite(s_max).any():
        panel.note("no valid pixels in the sample ROI")
        return
    runs = [slice(0, t.size)]
    panel.trace(t, s_mean, runs, MEAN_RGB, 4)
    panel.trace(t, s_max, runs, MAX_RGB, 4)
    if limit is not None:
        panel.dotted(limit, CEILING_RGB)


def _draw_dark(panel: _Panel, arr: RowArrays, runs: list[slice]) -> None:
    median = median_by_run(arr.dark_px, runs)
    raw = (*DARK_RGB, RAW_ALPHA)
    panel.legend([(raw, "sample_dark_px"), (DARK_RGB, f"{ROLLING_WINDOW}-frame rolling median")])
    panel.trace(arr.t, arr.dark_px, runs, raw, 2)
    panel.trace(arr.t, median, runs, DARK_RGB, 4)


def _draw_brightening(panel: _Panel, arr: RowArrays, runs: list[slice], events: bool) -> None:
    items: list[tuple[Colour | None, str]] = [(BRIGHT_RGB, "brightening (keyframes left out)")]
    if events:
        items.append((EVENT_RGB, "flash event, peak value"))
    panel.legend(items)
    panel.trace(arr.t, arr.brightening, runs, BRIGHT_RGB, 2)


def _fmt_adjust(value: float, signed: bool) -> str:
    """``value`` to 2 decimals, as the UI's adjusted status line shows it (``+`` when signed)."""
    r = round(float(value), 2) + 0.0  # + 0.0 turns -0.0 into 0.0
    text = f"{r:g}"
    return f"+{text}" if signed and r > 0 else text


def plot_title(summary: dict[str, Any]) -> str | None:
    """The title of the adjusted plot (the adjustment it measured), ``None`` for the raw plot.

    ``summary["adjust"]`` is what ``analyse_visible_sample`` records for the adjusted family; when
    its values are missing the title still says the plot is adjusted.
    """
    if "adjust" not in summary:
        return None
    a = summary.get("adjust")
    if not isinstance(a, dict):
        return "(adjusted)"
    try:
        ev, b, c = (float(a[k]) for k in ("exposure_ev", "brightness", "contrast"))
    except (KeyError, TypeError, ValueError):
        return "(adjusted)"
    return (
        f"(adjusted: exposure {_fmt_adjust(ev, True)} EV, brightness {_fmt_adjust(b, True)}, "
        f"contrast {_fmt_adjust(c, False)})"
    )


def visible_sample_plot_png(
    reader: ExperimentReader, rows: list[dict[str, Any]], summary: dict[str, Any]
) -> bytes:
    """The timeline plot as PNG bytes.

    ``rows`` and ``summary`` are what ``analyse_visible_sample`` holds for an analysed run (the
    CSV rows and the JSON): the per-frame rows, and ``sample_roi`` and ``events`` for the rest.
    The sample's temperatures come from ``reader``'s thermal store (in C when the recording is
    temperature-linear, otherwise in counts, and named so), the RF power from its ``control``
    events. Raises ``ValueError`` when the summary's sample ROI is not in the run.
    """
    events: list[dict[str, Any]] = list(summary.get("events") or [])
    arr = row_arrays(rows)
    runs = line_runs(arr.t, arr.segment)
    sample = _sample_roi(reader, summary)
    thermal = roi_series(reader, [sample])
    t_th = np.array(thermal["t_s"], dtype=float)
    stats = thermal["series"][str(sample["id"])]  # keyed by ROI id as a string
    s_max, s_mean = _floats(stats["max"]), _floats(stats["mean"])
    unit = unit_label(thermal["units"])
    limit = _reached_limit(reader, thermal["units"], s_max)
    control = control_series_from_rows(
        [e for e in reader.events if e.get("type") == "control"], reader.timeline()
    )
    t_rf, rf = np.array(control["t_s"], dtype=float), _floats(control.get("forward_w", []))

    last = max([float(a[-1]) for a in (t_th, arr.t) if a.size], default=0.0)
    canvas = _Canvas(last if last > 0 else 1.0)
    boxes = panel_boxes()
    limits = [
        _y_range(rf, zero=True),
        _y_range(s_max, s_mean, np.array([] if limit is None else [limit])),
        _y_range(arr.dark_px, zero=True),
        _y_range(arr.brightening, zero=True),
    ]
    panels = [
        _Panel(canvas, b, lim, last=i == N_PANELS - 1)
        for i, (b, lim) in enumerate(zip(boxes, limits, strict=True))
    ]
    for panel in panels:  # under the traces
        panel.event_lines(events)
    name = f"{sample.get('name') or 'sample ROI'} ({unit})"
    _draw_rf(panels[0], t_rf, rf)
    _draw_temperature(panels[1], t_th, s_max, s_mean, limit, name, unit)
    _draw_dark(panels[2], arr, runs)
    _draw_brightening(panels[3], arr, runs, bool(events))
    for panel in panels:  # over them
        panel.event_labels(events)
    label = "time since thermal frame 0 (s)"
    canvas.d.text((MARGIN_L, boxes[-1][1] + 48), label, fill=TICK_RGB, font=canvas.font)
    title = plot_title(summary)
    if title is not None:  # top right, level with the RF legend (which sits at the left)
        top = boxes[0][0] - LEGEND_ABOVE - 2
        canvas.d.text((canvas.x1, top), title, fill=LABEL_RGB, font=canvas.font, anchor="ra")
    buf = io.BytesIO()
    canvas.img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


__all__ = [
    "line_runs",
    "median_by_run",
    "panel_boxes",
    "plot_title",
    "rolling_median",
    "row_arrays",
    "unit_label",
    "visible_sample_plot_png",
]
