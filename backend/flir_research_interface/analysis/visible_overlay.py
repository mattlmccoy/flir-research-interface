"""Blend the recorded visible-camera video over the thermal frame for media export.

Playback shows the visible camera over the IR image via a stored visible→IR homography and keeps
the video's ``currentTime`` equal to the thermal elapsed time (host-clock aligned). This module
reproduces that for the exported clip: it pre-extracts the export window's visible frames in one
ffmpeg pass to a temp directory, warps each onto the IR frame with the homography, and alpha-blends
it at the chosen opacity. Warped frames are cached so a slow output fps never re-warps the same
source frame. Nothing here touches the store.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from types import TracebackType
from typing import Any

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

_MAX_EXTRACT_FPS = 10.0  # the visible stream is ~6 fps; never pull more than this


def ir_to_visible_coeffs(
    h_matrix: list[list[float]], out_w: float, out_h: float, vis_w: float, vis_h: float,
) -> tuple[float, float, float, float, float, float, float, float]:
    """PIL PERSPECTIVE coefficients mapping an output (IR-sized) pixel to a visible-image pixel.

    ``h_matrix`` is the stored visible→IR homography in *normalised* coordinates. We invert it and
    change basis to pixels: ir_pixel → ir_norm → visible_norm → visible_pixel. PIL's transform wants
    the destination→source map, which is exactly this.
    """
    h = np.asarray(h_matrix, dtype=float)
    inv = np.linalg.inv(h)  # ir_norm → visible_norm
    to_norm = np.diag([1.0 / out_w, 1.0 / out_h, 1.0])  # ir_pixel → ir_norm
    to_pix = np.diag([vis_w, vis_h, 1.0])  # visible_norm → visible_pixel
    m = to_pix @ inv @ to_norm  # ir_pixel → visible_pixel
    m = m / m[2, 2]
    return (m[0, 0], m[0, 1], m[0, 2], m[1, 0], m[1, 1], m[1, 2], m[2, 0], m[2, 1])


def _warp(frame_rgb: np.ndarray, coeffs: tuple[float, ...], out_w: int, out_h: int) -> np.ndarray:
    img = Image.fromarray(frame_rgb)
    warped = img.transform((out_w, out_h), Image.PERSPECTIVE, coeffs, resample=Image.BILINEAR)
    return np.asarray(warped, dtype=np.uint8)


class VisibleSource:
    """Pre-extracts the window's visible frames (one ffmpeg pass) and serves warped frames by time.

    ``out_w``/``out_h`` are the IR *body* size in the export (native × scale). Use as a context
    manager so the temp directory is removed. ``warped_at`` returns None when there is no frame.
    """

    def __init__(self, reader: Any, ffmpeg: str, t0: float, t1: float,
                 out_w: int, out_h: int) -> None:
        self._dir = tempfile.mkdtemp(prefix="fri_visible_")
        self._out_w, self._out_h = out_w, out_h
        self._times: list[float] = []
        self._files: list[str] = []
        self._cache: dict[int, np.ndarray] = {}
        vis = reader.metadata.get("visible") or {}
        align = reader.metadata.get("visible_alignment") or {}
        h_matrix = align.get("H")
        path = reader.path / (vis.get("file") or "visible.mp4")
        if not path.is_file() or not h_matrix:
            return  # no video or no alignment → overlay stays off
        vis_w = int(vis.get("width") or 1280)
        vis_h = int(vis.get("height") or 960)
        self._coeffs = ir_to_visible_coeffs(h_matrix, out_w, out_h, vis_w, vis_h)
        fps = min(_MAX_EXTRACT_FPS, max(1.0, float(vis.get("measured_fps") or 6.0)))
        dur = max(1.0 / fps, t1 - t0)
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{t0:.3f}", "-i", str(path),
               "-t", f"{dur:.3f}", "-vf", f"fps={fps:g}", "-q:v", "3",
               str(Path(self._dir) / "f_%05d.jpg")]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=600)
        except (subprocess.SubprocessError, OSError) as exc:  # keep export working without visible
            logger.warning("visible-overlay extract failed: %s", exc)
            return
        self._files = sorted(str(p) for p in Path(self._dir).glob("f_*.jpg"))
        self._times = [t0 + i / fps for i in range(len(self._files))]

    def warped_at(self, t: float) -> np.ndarray | None:
        if not self._files:
            return None
        i = min(range(len(self._times)), key=lambda k: abs(self._times[k] - t))
        cached = self._cache.get(i)
        if cached is not None:
            return cached
        try:
            frame = np.asarray(Image.open(self._files[i]).convert("RGB"), dtype=np.uint8)
        except OSError:
            return None
        warped = _warp(frame, self._coeffs, self._out_w, self._out_h)
        self._cache[i] = warped
        return warped

    def close(self) -> None:
        import shutil
        shutil.rmtree(self._dir, ignore_errors=True)

    def __enter__(self) -> VisibleSource:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        self.close()


def blend_visible(body: np.ndarray, warped: np.ndarray, opacity: float) -> np.ndarray:
    """Alpha-blend a warped visible frame over the thermal body region in place-safe fashion."""
    op = max(0.0, min(1.0, opacity))
    if op <= 0 or warped is None:
        return body
    h = min(body.shape[0], warped.shape[0])
    w = min(body.shape[1], warped.shape[1])
    out = body.astype(np.float32)
    out[:h, :w] = out[:h, :w] * (1.0 - op) + warped[:h, :w].astype(np.float32) * op
    return out.astype(np.uint8)


__all__ = ["VisibleSource", "ir_to_visible_coeffs", "blend_visible"]
