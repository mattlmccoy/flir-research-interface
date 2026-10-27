"""Synthetic smart-ROI recordings for tests (built with ``Recorder``; never touches PySpin)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from flir_research_interface.camera.base import Frame
from flir_research_interface.recording.recorder import Recorder

W, H = 160, 120
SEARCH = [[20, 20], [140, 20], [140, 100], [20, 100]]
SMART: dict[str, Any] = {"id": 7, "kind": "smart", "name": "part", "search": SEARCH}


def blob_celsius(i: int, *, cold: bool = False) -> np.ndarray:
    """150 °C ellipse growing 2 %/frame over 40 °C powder (falls off with distance)."""
    if cold:
        return np.full((H, W), 25.0)
    s = 1.0 + 0.02 * i
    rx, ry = 15.0 * s, 10.0 * s
    ys, xs = np.mgrid[0:H, 0:W]
    rho = np.sqrt(((xs - 80.0) / rx) ** 2 + ((ys - 60.0) / ry) ** 2)
    d = np.maximum(rho - 1.0, 0.0) * ry
    return np.where(rho <= 1.0, 150.0, 40.0 + 60.0 * np.exp(-d / 6.0))


def to_counts(c: np.ndarray) -> np.ndarray:
    return np.round((c + 273.15) * 100.0).astype(np.uint16)


def make_smart_run(
    root: Path,
    n: int = 8,
    *,
    frame_ids: Sequence[int] | None = None,
    rois: list[dict[str, Any]] | None = None,
    name: str = "smart",
    cold_frames: Sequence[int] = (0,),
) -> Path:
    """A recording whose frame ``i`` holds ``blob_celsius(i)`` (cold for ``cold_frames``)."""
    rec = Recorder(None, experiments_root=root, chunk_frames=4)
    d = rec.start(
        name=name,
        metadata={},
        camera_info={"backend": "simulated", "ir_format": "TemperatureLinear10mK", "model": "Sim"},
        extra={"rois": rois if rois is not None else [SMART]},
    )
    ids = list(frame_ids) if frame_ids is not None else [100 + i for i in range(n)]
    for i, fid in enumerate(ids):
        rec.submit(
            Frame(
                frame_id=fid,
                device_timestamp_ns=1_000_000_000 + i * 33_000_000,
                host_timestamp_ns=5_000_000_000 + i * 33_000_000,
                pixel_format="Mono16",
                ir_format="TemperatureLinear10mK",
                counts=to_counts(blob_celsius(i, cold=i in cold_frames)),
                incomplete=False,
            )
        )
    rec.stop()
    return d


OVERRANGE_FIXTURE = Path(__file__).parent / "fixtures" / "smart_overrange_20261020.npz"


def make_overrange_run(root: Path, *, high_c: float | None = None) -> tuple[Path, dict[str, Any]]:
    """A recording of the six real over-range frames (``smart_overrange_20261020.npz``, raw
    counts, 33 ms apart) with the run's ROI 113 (crop coordinates) and camera case. ``high_c``
    overrides the case ceiling; the camera info has no case at all when it is ``nan``."""
    fx = np.load(OVERRANGE_FIXTURE)
    ox, oy = (int(v) for v in fx["origin"])
    roi = {"id": 113, "kind": "smart", "name": "cube",
           "search": [[int(x) - ox, int(y) - oy] for x, y in fx["polygon"]],
           "rings_px": [int(r) for r in fx["rings_px"]]}
    high = float(fx["high_c"]) if high_c is None else high_c
    fmt = str(fx["ir_format"])
    cam: dict[str, Any] = {"backend": "simulated", "ir_format": fmt, "model": "Sim"}
    if not np.isnan(high):
        cam["active_case"] = {"index": 1, "low_c": -20.0, "high_c": high}
    rec = Recorder(None, experiments_root=root, chunk_frames=4)
    d = rec.start(name="overrange", metadata={}, camera_info=cam, extra={"rois": [roi]})
    for i, counts in enumerate(fx["counts"]):
        rec.submit(Frame(
            frame_id=100 + i, device_timestamp_ns=1_000_000_000 + i * 33_000_000,
            host_timestamp_ns=5_000_000_000 + i * 33_000_000, pixel_format="Mono16",
            ir_format=str(fx["ir_format"]), counts=np.ascontiguousarray(counts), incomplete=False,
        ))
    rec.stop()
    return d, roi
