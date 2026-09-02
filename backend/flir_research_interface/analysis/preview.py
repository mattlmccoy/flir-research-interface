"""Visualization-only preview images for experiments (spec §4).

``preview.png``  : the frame at 50 % of the recording, iron-like palette, auto-scaled to that frame.
``keyframes.png``: 12 frames at 0…100 %, tiled horizontally, one shared scale (whole-run min/max)
                   so the strip shows heating. Used for hover-scrub in the Experiments grid.

These files are derived products. They are written next to the store, listed in the manifest when
one exists, and can be regenerated at any time (``fri-thumbs``). They never modify the store.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import warnings
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from PIL import Image

from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.radiometry.temperature_linear import IRFormat, counts_to_celsius

PREVIEW_SIZE = (320, 240)
KEYFRAME_TILE = (160, 120)
KEYFRAME_COUNT = 12

_TEMPERATURE_LINEAR_FORMATS = {IRFormat.TEMPERATURE_LINEAR_10MK, IRFormat.TEMPERATURE_LINEAR_100MK}

# Same stops as frontend/src/lib/palette.ts (iron-like; not FLIR's LUT).
_IRON_STOPS = [
    (0.00, 0, 0, 0),
    (0.15, 32, 0, 96),
    (0.35, 140, 0, 140),
    (0.55, 220, 60, 40),
    (0.75, 250, 150, 20),
    (0.90, 255, 220, 60),
    (1.00, 255, 255, 230),
]


def _build_lut() -> npt.NDArray[np.uint8]:
    xs = np.array([s[0] for s in _IRON_STOPS])
    lut = np.zeros((256, 3), dtype=np.uint8)
    t = np.linspace(0, 1, 256)
    for c in range(3):
        ys = np.array([s[c + 1] for s in _IRON_STOPS], dtype=np.float64)
        lut[:, c] = np.clip(np.rint(np.interp(t, xs, ys)), 0, 255).astype(np.uint8)
    return lut


IRON_LUT: npt.NDArray[np.uint8] = _build_lut()


def _colorize(celsius: npt.NDArray[np.float32], vmin: float, vmax: float) -> npt.NDArray[np.uint8]:
    """Map a float array to RGB via ``IRON_LUT``. NaN is treated as ``vmin``; callers need not
    pre-clean their input. A degenerate (zero or negative) span renders as mid-gray (LUT index
    128) rather than the LUT's black endpoint, so a flat scene is distinguishable from a failed
    render.
    """
    celsius = np.nan_to_num(celsius, nan=vmin)
    span = vmax - vmin
    if span <= 0:
        idx = np.full(celsius.shape, 128, dtype=np.uint8)
    else:
        idx = np.clip(np.rint((celsius - vmin) * (255.0 / span)), 0, 255).astype(np.uint8)
    return IRON_LUT[idx]


def _downsample_max(
    celsius: npt.NDArray[np.float32], size: tuple[int, int]
) -> npt.NDArray[np.float32]:
    """Resize to ``size`` (PIL width, height convention), preserving hotspots.

    Shrinking uses block max-pooling (NaN-padded to a multiple of the block size, then
    ``nanmax`` per block) so a single hot pixel survives instead of being discarded or
    blurred by ordinary resampling; the pooled result is then resized to exactly ``size``
    with nearest-neighbour. Growing (or an exact match) uses nearest-neighbour directly.
    """
    h, w = celsius.shape
    tw, th = size
    if h <= th and w <= tw:
        img = Image.fromarray(celsius, mode="F").resize(size, Image.Resampling.NEAREST)
        return np.asarray(img, dtype=np.float32)

    bh = -(-h // th)  # ceil division: source rows per pooled row
    bw = -(-w // tw)  # ceil division: source cols per pooled col
    ph = ((h + bh - 1) // bh) * bh
    pw = ((w + bw - 1) // bw) * bw
    padded = np.full((ph, pw), np.nan, dtype=np.float32)
    padded[:h, :w] = celsius
    blocks = padded.reshape(ph // bh, bh, pw // bw, bw)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)  # all-NaN block, if any
        reduced = np.nanmax(blocks, axis=(1, 3))
    img = Image.fromarray(reduced.astype(np.float32), mode="F").resize(
        size, Image.Resampling.NEAREST
    )
    return np.asarray(img, dtype=np.float32)


def _png(rgb: npt.NDArray[np.uint8], size: tuple[int, int] | None) -> bytes:
    img = Image.fromarray(rgb, mode="RGB")
    if size is not None and img.size != size:
        img = img.resize(size, Image.Resampling.NEAREST)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_preview(
    celsius: npt.NDArray[np.float32], *, size: tuple[int, int] = PREVIEW_SIZE
) -> bytes:
    """PNG of one frame, auto-scaled to its own finite min/max. Downsampled by max-pooling
    (see :func:`_downsample_max`) so a small hotspot is not lost when shrinking.
    """
    finite = celsius[np.isfinite(celsius)]
    vmin, vmax = (float(finite.min()), float(finite.max())) if finite.size else (0.0, 1.0)
    downsampled = _downsample_max(celsius, size)
    return _png(_colorize(downsampled, vmin, vmax), size)


def render_keyframes(
    frames: Sequence[npt.NDArray[np.float32]],
    *,
    tile: tuple[int, int] = KEYFRAME_TILE,
    vmin: float,
    vmax: float,
) -> bytes:
    """Horizontal strip of frames on a shared scale.

    ``vmin``/``vmax`` are expected to be computed from the full-resolution frames (as
    :func:`generate_previews` does); that is always a safe bound here because max-pooling
    a frame down to ``tile`` never produces a value outside that frame's own range.
    """
    tiles = [_colorize(_downsample_max(f, tile), vmin, vmax) for f in frames]
    strip = np.concatenate(tiles, axis=1)
    return _png(strip, None)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    """Write ``data`` to a ``.tmp`` sibling then ``os.replace`` it into place, so a reader
    (or a crash mid-write) never observes a partially written file.
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def generate_previews(exp_dir: Path) -> dict[str, Any]:
    """Render preview.png + keyframes.png for an experiment.

    Updates ``manifest.previews`` if a manifest exists.
    """
    r = ExperimentReader(exp_dir)
    n = r.n_frames
    if n == 0:
        raise ValueError("experiment has no frames")
    try:
        fmt = IRFormat(r.ir_format) if r.ir_format else None
    except ValueError:
        fmt = None  # unknown/unsupported IRFormat string: fall back to raw-counts rendering
    units = "celsius" if fmt in _TEMPERATURE_LINEAR_FORMATS else "counts"

    def celsius(i: int) -> npt.NDArray[np.float32]:
        counts = r.frame(i).counts
        if fmt is None or fmt == IRFormat.RADIOMETRIC:
            return counts.astype(np.float32)  # raw counts; still a valid picture
        return counts_to_celsius(counts, fmt)

    mid = n // 2
    preview_png = render_preview(celsius(mid))
    indices = [int(round(k * (n - 1) / (KEYFRAME_COUNT - 1))) for k in range(KEYFRAME_COUNT)]
    frames = [celsius(i) for i in indices]
    stacked = np.stack(frames)
    if not np.isfinite(stacked).any():
        raise ValueError("no finite pixels")
    vmin = float(np.nanmin(stacked))
    vmax = float(np.nanmax(stacked))
    keyframes_png = render_keyframes(frames, vmin=vmin, vmax=vmax)

    _atomic_write(exp_dir / "preview.png", preview_png)
    _atomic_write(exp_dir / "keyframes.png", keyframes_png)
    out: dict[str, Any] = {
        "units": units,
        "preview": {
            "file": "preview.png",
            "frame_index": mid,
            "t_s": r.t_s(mid),
            "size": list(PREVIEW_SIZE),
            "units": units,
            "sha256": _sha256(preview_png),
        },
        "keyframes": {
            "file": "keyframes.png",
            "count": KEYFRAME_COUNT,
            "indices": indices,
            "t_s": [r.t_s(i) for i in indices],
            "tile": list(KEYFRAME_TILE),
            "units": units,
            "vmin": vmin,
            "vmax": vmax,
            "sha256": _sha256(keyframes_png),
        },
    }
    man_path = exp_dir / "manifest.json"
    if man_path.is_file():
        man = json.loads(man_path.read_text())
        man["previews"] = out
        _atomic_write(man_path, json.dumps(man, indent=2).encode())
    return out


__all__ = [
    "IRON_LUT",
    "KEYFRAME_COUNT",
    "KEYFRAME_TILE",
    "PREVIEW_SIZE",
    "generate_previews",
    "render_keyframes",
    "render_preview",
]
