"""Read-only access to a recorded experiment (Zarr v2 store + JSON sidecars).

The store is opened with ``mode="r"`` and every returned array is marked read-only, so
playback, palettes, ROIs and exports can never modify the canonical data (brief §1, §23).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import zarr

from flir_research_interface.camera.base import Frame
from flir_research_interface.recording.recorder import STORE_NAME, inspect_experiment


class ExperimentReader:
    """Open an experiment directory for playback."""

    def __init__(self, exp_dir: Path) -> None:
        self.path = Path(exp_dir)
        meta_path = self.path / "metadata.json"
        if not meta_path.is_file() or not (self.path / STORE_NAME).is_dir():
            raise FileNotFoundError(f"not an experiment directory: {self.path}")
        self.metadata: dict[str, Any] = json.loads(meta_path.read_text())
        man_path = self.path / "manifest.json"
        self.manifest: dict[str, Any] | None = (
            json.loads(man_path.read_text()) if man_path.is_file() else None
        )
        ev_path = self.path / "events.json"
        self.events: list[dict[str, Any]] = (
            json.loads(ev_path.read_text()) if ev_path.is_file() else []
        )
        vis_path = self.path / "visible.json"
        self.visible: dict[str, Any] | None = (
            json.loads(vis_path.read_text()) if vis_path.is_file() else None
        )
        pv_path = self.path / "previews.json"
        self._previews_sidecar: dict[str, Any] | None = (
            json.loads(pv_path.read_text()) if pv_path.is_file() else None
        )
        self._group = zarr.open_group(str(self.path / STORE_NAME), mode="r")
        self._counts = self._group["counts"]
        self._frame_id = np.asarray(self._group["frame_id"][:], dtype=np.int64)
        self._dev_ts = np.asarray(self._group["device_timestamp_ns"][:], dtype=np.int64)
        self._host_ts = np.asarray(self._group["host_timestamp_ns"][:], dtype=np.int64)
        n = min(
            int(self._counts.shape[0]), len(self._frame_id), len(self._dev_ts), len(self._host_ts)
        )
        self.n_frames = n  # tolerate a crash between array appends: use the common prefix
        self._t_s = (self._dev_ts[:n] - self._dev_ts[0]) / 1e9 if n else np.zeros(0)

    # -- metadata ------------------------------------------------------------------------------

    @property
    def ir_format(self) -> str | None:
        v = self.metadata.get("conversion", {}).get("ir_format") or self._counts.attrs.get(
            "ir_format"
        )
        return str(v) if v is not None else None

    @property
    def pixel_format(self) -> str:
        return str(self._counts.attrs.get("pixel_format", "Mono16"))

    def info(self) -> dict[str, Any]:
        insp = inspect_experiment(self.path)
        _, h, w = self._counts.shape
        return {
            "name": self.path.name,
            "path": str(self.path),
            "n_frames": self.n_frames,
            "width": int(w),
            "height": int(h),
            "duration_s": float(self._t_s[-1]) if self.n_frames else 0.0,
            "complete": insp["complete"],
            "manifest": self.manifest,
            "previews": (self.manifest or {}).get("previews") or self._previews_sidecar,
            "ir_format": self.ir_format,
            "pixel_format": self.pixel_format,
            "conversion": self.metadata.get("conversion"),
            "experiment": self.metadata.get("experiment"),
            "camera": self.metadata.get("camera"),
            "software": self.metadata.get("software"),
            "started_utc": self.metadata.get("started_utc"),
            "n_events": len(self.events),
            "visible": self.visible,
            "rois": self.metadata.get("rois"),
            "visible_alignment": self.metadata.get("visible_alignment"),
        }

    def timeline(self) -> dict[str, list[Any]]:
        return {
            "t_s": [float(x) for x in self._t_s],
            "frame_id": [int(x) for x in self._frame_id[: self.n_frames]],
        }

    def index_at(self, t_s: float) -> int:
        """Index of the frame nearest to relative time ``t_s``."""
        if self.n_frames == 0:
            raise IndexError("empty experiment")
        i = int(np.searchsorted(self._t_s, t_s))
        if i <= 0:
            return 0
        if i >= self.n_frames:
            return self.n_frames - 1
        return i if abs(self._t_s[i] - t_s) < abs(self._t_s[i - 1] - t_s) else i - 1

    # -- frames --------------------------------------------------------------------------------

    def frame(self, index: int) -> Frame:
        if not 0 <= index < self.n_frames:
            raise IndexError(f"frame index {index} out of range [0, {self.n_frames})")
        counts = np.asarray(self._counts[index], dtype=np.uint16)
        counts.setflags(write=False)
        return Frame(
            frame_id=int(self._frame_id[index]),
            device_timestamp_ns=int(self._dev_ts[index]),
            host_timestamp_ns=int(self._host_ts[index]),
            pixel_format=self.pixel_format,
            ir_format=str(self.ir_format or ""),
            counts=counts,
            incomplete=False,
        )

    def t_s(self, index: int) -> float:
        return float(self._t_s[index])

    def timestamps_ns(self) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.int64]]:
        """(device, host) timestamps in ns for the readable frames (copies)."""
        n = self.n_frames
        return self._dev_ts[:n].copy(), self._host_ts[:n].copy()

    def counts_block(self, start: int, stop: int) -> npt.NDArray[np.uint16]:
        """Frames ``[start, stop)`` as one read-only (n, h, w) uint16 array."""
        if not 0 <= start <= stop <= self.n_frames:
            raise IndexError(f"block [{start}, {stop}) out of range [0, {self.n_frames}]")
        block = np.asarray(self._counts[start:stop], dtype=np.uint16)
        block.setflags(write=False)
        return block


def list_experiments(root: Path) -> list[dict[str, Any]]:
    """Summaries of all experiment directories under ``root``, newest first."""
    root = Path(root)
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for d in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
        try:
            r = ExperimentReader(d)
        except (FileNotFoundError, KeyError, ValueError):
            insp = inspect_experiment(d)
            insp["name"] = d.name
            insp["n_frames"] = insp.get("frames_on_disk", 0)
            insp["error"] = "unreadable experiment"
            out.append(insp)
            continue
        info = r.info()
        info["frames_on_disk"] = info["n_frames"]
        info["metadata"] = {
            "experiment": info.get("experiment"),
            "conversion": info.get("conversion"),
            "started_utc": info.get("started_utc"),
        }
        info.pop("camera", None)
        info.pop("software", None)
        out.append(info)
    return out


__all__ = ["ExperimentReader", "list_experiments"]
