"""Derived thermal preview video: ``exports/thermal_preview.mp4``.

A small H.264 rendering of the whole run (iron palette, fixed °C scale for the run, colour bar and
elapsed-time label) so a recording can be opened, scrubbed and shared without any tool. It is a
*visualization*: the lossless record stays in ``thermal.zarr`` and this file can be regenerated
from it at any time. The colour scale is fixed to the run's min/max so brightness means the same
temperature in every frame.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from PIL import Image, ImageDraw, ImageFont

from flir_research_interface.analysis.preview import IRON_LUT, _colorize
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.radiometry.colormaps import INFERNO_LUT
from flir_research_interface.radiometry.temperature_linear import IRFormat, counts_to_celsius
from flir_research_interface.visible.recorder import FFMPEG_CANDIDATES
from flir_research_interface.visible.rtsp import find_ffprobe

logger = logging.getLogger(__name__)

OUT_NAME = "thermal_preview.mp4"
ROIS_OUT_NAME = "thermal_preview_rois.mp4"
BLOCK = 64  # frames per read from the store
MAX_FPS = 30.0
BAR_PX = 24  # width of the colour bar strip appended on the right
CRF = 27  # 2x-upscaled thermal noise compresses poorly; 27 keeps a 40 s run near 10 MB


def _celsius_frames(reader: ExperimentReader, start: int, stop: int) -> npt.NDArray[np.float32]:
    block = reader.counts_block(start, stop)
    fmt = reader.ir_format or ""
    if fmt in ("TemperatureLinear10mK", "TemperatureLinear100mK"):
        return np.asarray(counts_to_celsius(block, IRFormat(fmt)), dtype=np.float32)
    return block.astype(np.float32)


def run_range(reader: ExperimentReader, *, robust: bool = False) -> tuple[float, float, str]:
    """(vmin, vmax, units) over the whole run, ignoring NaN; ``units`` is 'celsius' or 'counts'.

    ``robust`` uses the 0.5th and 99.9th percentiles of every 8th frame instead of the extremes,
    so a single hot pixel does not crush the rest of the scene to black in viewing copies.
    """
    lo, hi = np.inf, -np.inf
    samples: list[npt.NDArray[np.float32]] = []
    for s in range(0, reader.n_frames, BLOCK):
        c = _celsius_frames(reader, s, min(s + BLOCK, reader.n_frames))
        if c.size:
            lo, hi = min(lo, float(np.nanmin(c))), max(hi, float(np.nanmax(c)))
            if robust:
                samples.append(c[::8].reshape(-1))
    if robust and samples:
        allv = np.concatenate(samples)
        allv = allv[np.isfinite(allv)]
        if allv.size:
            p_lo, p_hi = float(np.percentile(allv, 0.5)), float(np.percentile(allv, 99.95))
            if p_hi - p_lo >= 1.0:
                lo, hi = p_lo, p_hi
    fmt = reader.ir_format or ""
    units = "celsius" if fmt.startswith("TemperatureLinear") else "counts"
    if not np.isfinite(lo):
        lo, hi = 0.0, 1.0
    return lo, hi, units


def label_font(size: int = 14) -> ImageFont.FreeTypeFont:
    """Pillow's bundled TrueType face: has ° (the bitmap default draws a box; it lacks – too)."""
    font = ImageFont.load_default(size=size)
    if not isinstance(font, ImageFont.FreeTypeFont):  # pragma: no cover - Pillow < 10.1
        raise RuntimeError("Pillow >= 10.1 is required for the bundled TrueType font")
    return font


def _bar_ticks(lo: float, hi: float, target: int = 6) -> list[float]:
    """A short list of round tick temperatures spanning [lo, hi] (1/2/5 × 10^k spacing)."""
    import math
    span = hi - lo
    if span <= 0:
        return [lo]
    raw = span / max(1, target)
    mag = 10.0 ** math.floor(math.log10(raw))
    step = next((m * mag for m in (1, 2, 5, 10) if m * mag >= raw), 10 * mag)
    start = math.ceil(lo / step) * step
    out, t = [], start
    while t <= hi + step * 1e-6:
        out.append(round(t, 6))
        t += step
    return out or [lo, hi]


def thermal_frame_rgb(
    values: npt.NDArray[np.float32],
    vmin: float,
    vmax: float,
    t_s: float,
    bar_px: int = BAR_PX,
    *,
    scale: int = 1,
    rois: list[dict[str, Any]] | None = None,
    reader: ExperimentReader | None = None,
    show_time: bool = True,
    palette: str | None = None,
) -> npt.NDArray[np.uint8]:
    """Colourised frame plus a vertical colour bar (vmax at the top) and labels: (h, w+bar, 3).

    ``show_time`` draws the elapsed-time label at top-left (media export gates it on its own
    timestamp toggle); the derived preview video always shows it.
    """
    from flir_research_interface.analysis.annotate import colorize, draw_rois, roi_values_at

    h0, w0 = values.shape
    h, w = h0 * scale, w0 * scale
    img = np.zeros((h, w + bar_px, 3), dtype=np.uint8)
    ramp = np.linspace(255, 0, h).astype(np.uint8)  # top = hot
    if palette:  # explicit palette selection (export/media): same LUT for the body and the bar
        from flir_research_interface.analysis.palettes import apply_lut, palette_lut
        lut = palette_lut(palette)
        body = apply_lut(values, vmin, vmax, lut)
    else:
        body = colorize(values, vmin, vmax) if scale > 1 or rois else _colorize(values, vmin, vmax)
        lut = INFERNO_LUT if (scale > 1 or rois) else IRON_LUT
    img[:, :w] = np.repeat(np.repeat(body, scale, axis=0), scale, axis=1) if scale > 1 else body
    img[:, w:] = lut[ramp][:, None, :]
    pil = Image.fromarray(img)
    if rois and reader is not None:
        draw_rois(pil, rois, scale=scale, values=roi_values_at(reader, values, rois))
    d = ImageDraw.Draw(pil, "RGBA")
    font = label_font(max(10, min(16, h // 30)))
    if show_time:
        d.text((4, 2), f"{t_s:.2f} s", fill=(255, 255, 255), font=font)
    d.text((4, h - font.size - 4), f"{vmin:.1f} to {vmax:.1f} °C", fill=(255, 255, 255), font=font)
    if bar_px >= 12 and vmax > vmin:  # temperature tick labels beside the colour bar
        for tv in _bar_ticks(vmin, vmax):
            ty = min(max(0.0, h * (vmax - tv) / (vmax - vmin)), h - 1.0)
            d.line((w, ty, w + 5, ty), fill=(255, 255, 255))  # tick into the bar
            lbl = f"{tv:.0f}"
            tw = d.textlength(lbl, font=font)
            tx = w - tw - 4
            d.rectangle((tx - 2, ty - font.size / 2 - 1, tx + tw + 1, ty + font.size / 2 + 1),
                        fill=(0, 0, 0, 150))
            d.text((tx, ty - font.size / 2), lbl, fill=(255, 255, 255), font=font)
    return np.asarray(pil, dtype=np.uint8)


def encode_command(ffmpeg: str, width: int, height: int, fps: float, out: Path) -> list[str]:
    """ffmpeg command reading raw RGB frames from stdin and writing a web-friendly H.264 MP4."""
    fps_txt = f"{fps:g}"
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        fps_txt,
        "-i",
        "-",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        str(CRF),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(out),
    ]


def _fps(reader: ExperimentReader) -> float:
    n = reader.n_frames
    if n < 2:
        return 10.0
    dur = reader.t_s(n - 1) - reader.t_s(0)
    fps = (n - 1) / dur if dur > 0 else 10.0
    return float(min(max(fps, 1.0), MAX_FPS))


def render_thermal_video(
    reader: ExperimentReader,
    ffmpeg: str | None = None,
    *,
    scale: int = 2,
    with_rois: bool = False,
    out_name: str | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Render ``exports/thermal_preview.mp4`` (or ``out_name``) for ``reader``.

    ``scale`` upsamples the native frame (2 → 1280x960 for the A70); ``with_rois`` draws the
    stored ROIs with their live value on every frame (the file ``thermal_preview_rois.mp4``).
    ``on_progress(frames_done, frame_count)`` is called as encoding proceeds (this is the slow
    step) so a caller can show a determinate progress bar.

    Raises ``RuntimeError`` when ffmpeg is missing or fails, ``ValueError`` on an empty run.
    """
    if reader.n_frames == 0:
        raise ValueError("empty recording: nothing to render")
    ffmpeg = ffmpeg or find_ffprobe(FFMPEG_CANDIDATES)
    if ffmpeg is None:
        raise RuntimeError("ffmpeg not found")
    vmin, vmax, units = run_range(reader, robust=True)
    fps = _fps(reader)
    _, h, w = reader.counts_block(0, 1).shape
    rois = (reader.metadata.get("rois") or []) if with_rois else []
    width, height = w * scale + BAR_PX, h * scale
    if width % 2 or height % 2:  # yuv420p requires even dimensions
        width += width % 2
        height += height % 2
    out_dir = reader.path / "exports"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / (out_name or (ROIS_OUT_NAME if with_rois else OUT_NAME))
    tmp = out.with_suffix(".part.mp4")
    cmd = encode_command(ffmpeg, width, height, fps, tmp)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        for s in range(0, reader.n_frames, BLOCK):
            block = _celsius_frames(reader, s, min(s + BLOCK, reader.n_frames))
            for j, frame in enumerate(block):
                rgb = thermal_frame_rgb(
                    frame, vmin, vmax, reader.t_s(s + j), scale=scale, rois=rois, reader=reader
                )
                if rgb.shape[0] != height or rgb.shape[1] != width:
                    pad = np.zeros((height, width, 3), dtype=np.uint8)
                    pad[: rgb.shape[0], : rgb.shape[1]] = rgb
                    rgb = pad
                proc.stdin.write(np.ascontiguousarray(rgb).tobytes())
            if on_progress is not None:
                on_progress(min(s + BLOCK, reader.n_frames), reader.n_frames)
    except BrokenPipeError:
        pass  # ffmpeg died early; its stderr explains why (reported below)
    _, err = proc.communicate(timeout=300)  # closes stdin, drains stderr, waits
    if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        tail = err.decode(errors="replace")[-400:]
        raise RuntimeError(f"ffmpeg failed (rc {proc.returncode}): {tail}")
    tmp.replace(out)
    info = {
        "path": str(out),
        "frames": reader.n_frames,
        "fps": fps,
        "width": width,
        "height": height,
        "vmin": vmin,
        "vmax": vmax,
        "units": units,
        "bytes": out.stat().st_size,
    }
    logger.info("thermal preview video written: %s", info)
    return info


__all__ = [
    "OUT_NAME",
    "ROIS_OUT_NAME",
    "encode_command",
    "label_font",
    "render_thermal_video",
    "run_range",
    "thermal_frame_rgb",
]
