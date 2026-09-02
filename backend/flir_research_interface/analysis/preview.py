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
    span = vmax - vmin
    if span <= 0:
        idx = np.zeros(celsius.shape, dtype=np.uint8)
    else:
        idx = np.clip(np.rint((celsius - vmin) * (255.0 / span)), 0, 255).astype(np.uint8)
    return IRON_LUT[idx]


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
    """PNG of one frame, auto-scaled to its own finite min/max."""
    finite = celsius[np.isfinite(celsius)]
    vmin, vmax = (float(finite.min()), float(finite.max())) if finite.size else (0.0, 1.0)
    return _png(_colorize(np.nan_to_num(celsius, nan=vmin), vmin, vmax), size)


def render_keyframes(
    frames: list[npt.NDArray[np.float32]],
    *,
    tile: tuple[int, int] = KEYFRAME_TILE,
    vmin: float,
    vmax: float,
) -> bytes:
    """Horizontal strip of frames on a shared scale."""
    tiles = []
    for f in frames:
        rgb = _colorize(np.nan_to_num(f, nan=vmin), vmin, vmax)
        tiles.append(
            np.asarray(Image.fromarray(rgb, mode="RGB").resize(tile, Image.Resampling.NEAREST))
        )
    strip = np.concatenate(tiles, axis=1)
    return _png(strip, None)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def generate_previews(exp_dir: Path) -> dict[str, Any]:
    """Render preview.png + keyframes.png for an experiment.

    Updates ``manifest.previews`` if a manifest exists.
    """
    r = ExperimentReader(exp_dir)
    n = r.n_frames
    if n == 0:
        raise ValueError("experiment has no frames")
    fmt = IRFormat(r.ir_format) if r.ir_format else None

    def celsius(i: int) -> npt.NDArray[np.float32]:
        counts = r.frame(i).counts
        if fmt is None or fmt == IRFormat.RADIOMETRIC:
            return counts.astype(np.float32)  # raw counts; still a valid picture
        return counts_to_celsius(counts, fmt)

    mid = n // 2
    preview_png = render_preview(celsius(mid))
    indices = sorted(
        {int(round(k * (n - 1) / (KEYFRAME_COUNT - 1))) for k in range(KEYFRAME_COUNT)}
    )
    while len(indices) < KEYFRAME_COUNT:  # short runs: repeat last index
        indices.append(indices[-1])
    frames = [celsius(i) for i in indices]
    vmin = float(min(np.nanmin(f) for f in frames))
    vmax = float(max(np.nanmax(f) for f in frames))
    keyframes_png = render_keyframes(frames, vmin=vmin, vmax=vmax)

    (exp_dir / "preview.png").write_bytes(preview_png)
    (exp_dir / "keyframes.png").write_bytes(keyframes_png)
    out: dict[str, Any] = {
        "preview": {
            "file": "preview.png",
            "frame_index": mid,
            "t_s": r.t_s(mid),
            "size": list(PREVIEW_SIZE),
            "sha256": _sha256(preview_png),
        },
        "keyframes": {
            "file": "keyframes.png",
            "count": KEYFRAME_COUNT,
            "indices": indices,
            "t_s": [r.t_s(i) for i in indices],
            "tile": list(KEYFRAME_TILE),
            "vmin_c": vmin,
            "vmax_c": vmax,
            "sha256": _sha256(keyframes_png),
        },
    }
    man_path = exp_dir / "manifest.json"
    if man_path.is_file():
        man = json.loads(man_path.read_text())
        man["previews"] = out
        man_path.write_text(json.dumps(man, indent=2))
    return out


__all__ = ["IRON_LUT", "KEYFRAME_COUNT", "generate_previews", "render_keyframes", "render_preview"]
