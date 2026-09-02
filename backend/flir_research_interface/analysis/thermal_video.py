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
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from PIL import Image, ImageDraw, ImageFont

from flir_research_interface.analysis.preview import IRON_LUT, _colorize
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.radiometry.temperature_linear import IRFormat, counts_to_celsius
from flir_research_interface.visible.recorder import FFMPEG_CANDIDATES
from flir_research_interface.visible.rtsp import find_ffprobe

logger = logging.getLogger(__name__)

OUT_NAME = "thermal_preview.mp4"
BLOCK = 64  # frames per read from the store
MAX_FPS = 30.0
BAR_PX = 24  # width of the colour bar strip appended on the right
CRF = 23


def _celsius_frames(reader: ExperimentReader, start: int, stop: int) -> npt.NDArray[np.float32]:
    block = reader.counts_block(start, stop)
    fmt = reader.ir_format or ""
    if fmt in ("TemperatureLinear10mK", "TemperatureLinear100mK"):
        return np.asarray(counts_to_celsius(block, IRFormat(fmt)), dtype=np.float32)
    return block.astype(np.float32)


def run_range(reader: ExperimentReader) -> tuple[float, float, str]:
    """(vmin, vmax, units) over the whole run, ignoring NaN; ``units`` is 'celsius' or 'counts'."""
    lo, hi = np.inf, -np.inf
    for s in range(0, reader.n_frames, BLOCK):
        c = _celsius_frames(reader, s, min(s + BLOCK, reader.n_frames))
        if c.size:
            lo, hi = min(lo, float(np.nanmin(c))), max(hi, float(np.nanmax(c)))
    fmt = reader.ir_format or ""
    units = "celsius" if fmt.startswith("TemperatureLinear") else "counts"
    if not np.isfinite(lo):
        lo, hi = 0.0, 1.0
    return lo, hi, units


def label_font(size: int = 14) -> ImageFont.FreeTypeFont:
    """Pillow's bundled TrueType face: has ° and – (the bitmap default draws boxes for them)."""
    font = ImageFont.load_default(size=size)
    if not isinstance(font, ImageFont.FreeTypeFont):  # pragma: no cover - Pillow < 10.1
        raise RuntimeError("Pillow >= 10.1 is required for the bundled TrueType font")
    return font


def thermal_frame_rgb(
    values: npt.NDArray[np.float32], vmin: float, vmax: float, t_s: float, bar_px: int = BAR_PX
) -> npt.NDArray[np.uint8]:
    """Colourised frame plus a vertical colour bar (vmax at the top) and labels: (h, w+bar, 3)."""
    h, w = values.shape
    img = np.zeros((h, w + bar_px, 3), dtype=np.uint8)
    img[:, :w] = _colorize(values, vmin, vmax)
    ramp = np.linspace(255, 0, h).astype(np.uint8)  # top = hot
    img[:, w:] = IRON_LUT[ramp][:, None, :]
    pil = Image.fromarray(img)
    d = ImageDraw.Draw(pil)
    font = label_font(max(10, min(16, h // 30)))
    d.text((4, 2), f"{t_s:.2f} s", fill=(255, 255, 255), font=font)
    d.text((4, h - font.size - 4), f"{vmin:.1f} – {vmax:.1f} °C", fill=(255, 255, 255), font=font)
    return np.asarray(pil, dtype=np.uint8)


def encode_command(ffmpeg: str, width: int, height: int, fps: float, out: Path) -> list[str]:
    """ffmpeg command reading raw RGB frames from stdin and writing a web-friendly H.264 MP4."""
    fps_txt = f"{fps:g}"
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", fps_txt, "-i", "-",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(CRF), "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(out),
    ]


def _fps(reader: ExperimentReader) -> float:
    n = reader.n_frames
    if n < 2:
        return 10.0
    dur = reader.t_s(n - 1) - reader.t_s(0)
    fps = (n - 1) / dur if dur > 0 else 10.0
    return float(min(max(fps, 1.0), MAX_FPS))


def render_thermal_video(reader: ExperimentReader, ffmpeg: str | None = None) -> dict[str, Any]:
    """Render ``exports/thermal_preview.mp4`` for ``reader``; returns a summary dict.

    Raises ``RuntimeError`` when ffmpeg is missing or fails, ``ValueError`` on an empty run.
    """
    if reader.n_frames == 0:
        raise ValueError("empty recording: nothing to render")
    ffmpeg = ffmpeg or find_ffprobe(FFMPEG_CANDIDATES)
    if ffmpeg is None:
        raise RuntimeError("ffmpeg not found")
    vmin, vmax, units = run_range(reader)
    fps = _fps(reader)
    _, h, w = reader.counts_block(0, 1).shape
    width, height = w + BAR_PX, h
    if width % 2 or height % 2:  # yuv420p requires even dimensions
        width += width % 2
        height += height % 2
    out_dir = reader.path / "exports"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / OUT_NAME
    tmp = out.with_suffix(".part.mp4")
    cmd = encode_command(ffmpeg, width, height, fps, tmp)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        for s in range(0, reader.n_frames, BLOCK):
            block = _celsius_frames(reader, s, min(s + BLOCK, reader.n_frames))
            for j, frame in enumerate(block):
                rgb = thermal_frame_rgb(frame, vmin, vmax, reader.t_s(s + j))
                if rgb.shape[0] != height or rgb.shape[1] != width:
                    pad = np.zeros((height, width, 3), dtype=np.uint8)
                    pad[: rgb.shape[0], : rgb.shape[1]] = rgb
                    rgb = pad
                proc.stdin.write(np.ascontiguousarray(rgb).tobytes())
    except BrokenPipeError:
        pass  # ffmpeg died early; its stderr explains why (reported below)
    _, err = proc.communicate(timeout=300)  # closes stdin, drains stderr, waits
    if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        tail = err.decode(errors="replace")[-400:]
        raise RuntimeError(f"ffmpeg failed (rc {proc.returncode}): {tail}")
    tmp.replace(out)
    info = {
        "path": str(out), "frames": reader.n_frames, "fps": fps, "width": width, "height": height,
        "vmin": vmin, "vmax": vmax, "units": units, "bytes": out.stat().st_size,
    }
    logger.info("thermal preview video written: %s", info)
    return info


__all__ = [
    "OUT_NAME",
    "encode_command",
    "label_font",
    "render_thermal_video",
    "run_range",
    "thermal_frame_rgb",
]
