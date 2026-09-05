"""Media export: render a chosen time window of a run to MP4 or GIF with optional overlays.

Builds on the thermal-video frame compositor (palette + colour bar + elapsed time + ROIs) and adds
a title caption, a whole-frame min/max/mean readout, and — for GIF — a two-pass palette for clean
colours with a frame-count guard. See the media-export design spec under docs/superpowers/specs/.
"""

from __future__ import annotations

import logging
import math
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from flir_research_interface.analysis.thermal_video import (
    FFMPEG_CANDIDATES,
    encode_command,
    label_font,
    run_range,
    thermal_frame_rgb,
)
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.radiometry.overrange import over_range_mask
from flir_research_interface.radiometry.temperature_linear import IRFormat, counts_to_celsius
from flir_research_interface.visible.rtsp import find_ffprobe

logger = logging.getLogger(__name__)

MAX_GIF_FRAMES = 300  # size guard: subsample so a GIF cannot balloon
CLIPS_DIR = "clips"


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


def _slug(text: str) -> str:
    keep = "".join(c if c.isalnum() or c in "-_ " else "" for c in text).strip().replace(" ", "_")
    return keep[:48] or "clip"


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

    vmin, vmax, _units = run_range(reader, robust=True)
    _, h0, w0 = reader.counts_block(0, 1).shape
    scale = max(1, opts.scale)
    rois = (reader.metadata.get("rois") or []) if opts.with_rois else []

    # size the first frame to fix the encoder geometry
    first = _compose(reader, indices[0], vmin, vmax, scale, rois, opts)
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
            rgb = first if k == 0 else _compose(reader, idx, vmin, vmax, scale, rois, opts)
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
    info.update({"path": str(out), "name": out.name, "frames": total, "fps": out_fps,
                 "width": width, "height": height, "bytes": out.stat().st_size, "note": guard_note})
    logger.info("media clip written: %s", info)
    return info


def _compose(reader: ExperimentReader, idx: int, vmin: float, vmax: float, scale: int,
             rois: list[dict[str, Any]], opts: MediaOptions) -> np.ndarray:
    values, counts = _celsius(reader, idx)
    over = over_range_mask(counts)
    stats_vals = values if over is None else np.where(over, np.nan, values)
    bar = 24 if opts.colorbar else 0
    rgb = thermal_frame_rgb(values, vmin, vmax, reader.t_s(idx), bar_px=bar, scale=scale,
                            rois=rois if opts.with_rois else None, reader=reader)
    if over is not None:  # paint over-range pixels magenta, like the live display
        big = np.repeat(np.repeat(over, scale, axis=0), scale, axis=1)
        rgb[: big.shape[0], : big.shape[1]][big] = (255, 0, 255)
    pil = Image.fromarray(rgb)
    d = ImageDraw.Draw(pil)
    font = label_font(max(11, min(18, rgb.shape[0] // 26)))
    if opts.frame_stats:
        lo, hi, mean = np.nanmin(stats_vals), np.nanmax(stats_vals), np.nanmean(stats_vals)
        txt = f"min {lo:.1f}  max {hi:.1f}  mean {mean:.1f} °C"
        d.text((4, rgb.shape[0] - 2 * font.size - 8), txt, fill=(255, 255, 255), font=font)
    if opts.title:
        tw = d.textlength(opts.title, font=font)
        d.rectangle((0, 0, rgb.shape[1], font.size + 8), fill=(0, 0, 0))
        d.text(((rgb.shape[1] - tw) / 2, 3), opts.title, fill=(255, 255, 255), font=font)
    return np.asarray(pil, dtype=np.uint8)


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
    tmp = out.with_suffix(".part.mp4")
    proc = subprocess.Popen(encode_command(ffmpeg, width, height, fps, tmp),
                            stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    _pump(proc, frames, total, on_progress)
    _, err = proc.communicate(timeout=600)
    if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        tail = err.decode(errors="replace")[-400:]
        raise RuntimeError(f"ffmpeg failed (rc {proc.returncode}): {tail}")
    tmp.replace(out)
    return {}


def _encode_gif(  # type: ignore[no-untyped-def]
    ffmpeg, width, height, fps, out, frames, total, on_progress
) -> dict[str, Any]:
    # write raw frames once, then two-pass palettegen/paletteuse for clean colours
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
        tmp = out.with_suffix(".part.gif")
        r = subprocess.run([*base, "-i", str(pal), "-lavfi",
                            "paletteuse=dither=bayer:bayer_scale=3", str(tmp)],
                           capture_output=True, timeout=600)
        if r.returncode != 0 or not tmp.is_file():
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"gif encode failed: {r.stderr.decode(errors='replace')[-400:]}")
        tmp.replace(out)
    return {}


def compose_preview(reader: ExperimentReader, opts: MediaOptions, index: int) -> bytes:
    """One composed frame (same overlays as the export) as PNG bytes for the live preview."""
    if not (0 <= index < reader.n_frames):
        raise ValueError(f"index out of range 0..{reader.n_frames - 1}")
    vmin, vmax, _ = run_range(reader, robust=True)
    rois = (reader.metadata.get("rois") or []) if opts.with_rois else []
    rgb = _compose(reader, index, vmin, vmax, max(1, opts.scale), rois, opts)
    from io import BytesIO

    buf = BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG")
    return buf.getvalue()


__all__ = ["MediaOptions", "render_clip", "compose_preview", "MAX_GIF_FRAMES"]
