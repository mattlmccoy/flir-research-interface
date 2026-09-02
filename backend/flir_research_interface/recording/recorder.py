"""Scientific recorder: bounded queue -> writer thread -> Zarr v2 store on disk.

Data-integrity rules implemented here (brief §16, §17, §18, §28):

* The camera thread only *enqueues* (never blocks). If the bounded queue is full the frame is
  dropped **and counted** (``queue_dropped``); such a recording is flagged ``complete=False``.
* Frame-id gaps (frames the camera/transport never delivered) are detected and listed.
* Every frame stores ``frame_id``, ``device_timestamp_ns`` and ``host_timestamp_ns``.
* ``metadata.json`` (camera info, software version, git commit, host, conversion rule) is written
  at start; ``manifest.json`` only at clean finalization, so an experiment without a manifest is
  detectably incomplete. Zarr chunks are written atomically by the store, so a crash loses at
  most the frames still in memory.
* A free-space guard refuses to start below ``min_free_gb`` and stops the recording (state
  ``ERROR``) if space runs out mid-run; what was written stays readable.

Layout::

    experiments/<YYYYMMDD_HHMMSS>_<name>/
        metadata.json      camera + software + experiment metadata
        thermal.zarr/      counts[t,y,x] uint16 (zstd), frame_id[t],
                           device_timestamp_ns[t], host_timestamp_ns[t]
        events.json        recorder events (start/stop/gaps/errors); user annotations later (M8)
        manifest.json      written on finalize: counts, gaps, drops, complete flag, checksums
"""

from __future__ import annotations

import enum
import hashlib
import json
import logging
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import zarr
from numcodecs import Blosc

from flir_research_interface import __version__
from flir_research_interface.acquisition.service import AcquisitionService
from flir_research_interface.camera.base import Frame
from flir_research_interface.radiometry.temperature_linear import (
    KELVIN_OFFSET,
    IRFormat,
    kelvin_per_count,
)

logger = logging.getLogger(__name__)

STORE_NAME = "thermal.zarr"
FORMAT_VERSION = "1"


class RecorderState(str, enum.Enum):
    IDLE = "idle"
    RECORDING = "recording"
    FINALIZING = "finalizing"
    ERROR = "error"


def _git_commit() -> str | None:
    try:
        root = Path(__file__).resolve().parents[3]
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5
        )
        return out.stdout.strip() or None if out.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _default_free_space_gb(path: Path) -> float:
    target = path if path.exists() else path.parent
    return shutil.disk_usage(target).free / 1e9


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip()).strip("_")
    return s or "experiment"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inspect_experiment(exp_dir: Path) -> dict[str, Any]:
    """Describe an experiment directory: completeness, frames on disk, metadata presence."""
    info: dict[str, Any] = {
        "path": str(exp_dir),
        "has_metadata": (exp_dir / "metadata.json").is_file(),
        "manifest": None,
        "complete": False,
        "frames_on_disk": 0,
    }
    man_path = exp_dir / "manifest.json"
    if man_path.is_file():
        info["manifest"] = json.loads(man_path.read_text())
        info["complete"] = bool(info["manifest"].get("complete", False))
    store = exp_dir / STORE_NAME
    if store.is_dir():
        try:
            g = zarr.open_group(str(store), mode="r")
            info["frames_on_disk"] = int(g["counts"].shape[0])
            info["shape"] = list(g["counts"].shape)
        except Exception as exc:  # noqa: BLE001
            info["store_error"] = f"{type(exc).__name__}: {exc}"
    return info


class Recorder:
    """Records frames from an :class:`AcquisitionService` (or via :meth:`submit`) to disk."""

    def __init__(
        self,
        service: AcquisitionService | None,
        *,
        experiments_root: Path,
        chunk_frames: int = 32,
        queue_frames: int = 600,
        min_free_gb: float = 2.0,
        free_space_gb: Callable[[Path], float] = _default_free_space_gb,
        compressor: Any | None = None,
        flush_interval_s: float = 0.5,
    ) -> None:
        self._service = service
        self._root = Path(experiments_root)
        self._chunk = chunk_frames
        self._queue: queue.Queue[Frame | None] = queue.Queue(maxsize=queue_frames)
        self._min_free_gb = min_free_gb
        self._free_space_gb = free_space_gb
        self._compressor = compressor or Blosc(cname="zstd", clevel=3, shuffle=Blosc.BITSHUFFLE)
        self._flush_interval_s = flush_interval_s
        self._buf_started: float | None = None
        self._state = RecorderState.IDLE
        self._lock = threading.Lock()
        self._writer: threading.Thread | None = None
        self._pause = threading.Event()
        self._pause.set()  # set == running
        self._exp_dir: Path | None = None
        self._group: Any = None
        self._listener_attached = False
        self._counts_arr: Any = None
        self._reset_counters()

    def _reset_counters(self) -> None:
        self._frames_received = 0
        self._frames_written = 0
        self._queue_dropped = 0
        self._gap_events: list[dict[str, int]] = []
        self._last_frame_id: int | None = None
        self._last_submitted_id: int | None = None
        self._first_ts: int | None = None
        self._last_ts: int | None = None
        self._error: str | None = None
        self._events: list[dict[str, Any]] = []
        self._buf: list[Frame] = []
        self._started_at: str | None = None

    # -- public ------------------------------------------------------------------------------

    @property
    def state(self) -> RecorderState:
        return self._state

    @property
    def experiment_dir(self) -> Path | None:
        return self._exp_dir

    def stats(self) -> dict[str, Any]:
        with self._lock:
            dur = (
                (self._last_ts - self._first_ts) / 1e9
                if self._first_ts is not None and self._last_ts
                else 0.0
            )
            return {
                "state": self._state.value,
                "experiment_dir": str(self._exp_dir) if self._exp_dir else None,
                "frames_received": self._frames_received,
                "frames_written": self._frames_written,
                "queue_depth": self._queue.qsize(),
                "queue_dropped": self._queue_dropped,
                "frame_id_gaps": sum(g["missing"] for g in self._gap_events),
                "duration_s": dur,
                "recorded_fps": (self._frames_written - 1) / dur
                if dur > 0 and self._frames_written > 1
                else None,
                "free_space_gb": self._free_space_gb(self._exp_dir or self._root)
                if self._root
                else None,
                "min_free_gb": self._min_free_gb,
                "error": self._error,
            }

    def start(
        self, *, name: str, metadata: dict[str, Any], camera_info: dict[str, Any] | None = None
    ) -> Path:
        if self._state == RecorderState.RECORDING:
            raise RuntimeError("already recording")
        self._root.mkdir(parents=True, exist_ok=True)
        free = self._free_space_gb(self._root)
        if free < self._min_free_gb:
            raise RuntimeError(
                f"insufficient free space: {free:.2f} GB < {self._min_free_gb} GB minimum"
            )
        if camera_info is None:
            if self._service is None:
                raise RuntimeError("camera_info required when no service is attached")
            camera_info = self._service.backend.camera_info()

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        exp_dir = self._root / f"{stamp}_{_slug(name)}"
        n = 1
        while exp_dir.exists():
            n += 1
            exp_dir = self._root / f"{stamp}_{_slug(name)}_{n}"
        exp_dir.mkdir(parents=True)
        self._reset_counters()
        self._exp_dir = exp_dir
        self._started_at = datetime.now(timezone.utc).isoformat()

        ir_format = camera_info.get("ir_format")
        try:
            k = kelvin_per_count(IRFormat(ir_format)) if ir_format else None
        except ValueError:
            k = None
        meta = {
            "format_version": FORMAT_VERSION,
            "started_utc": self._started_at,
            "experiment": {"name": name, **metadata},
            "camera": camera_info,
            "conversion": {
                "ir_format": ir_format,
                "kelvin_per_count": k,
                "kelvin_offset": KELVIN_OFFSET,
                "rule": "T_C = counts * kelvin_per_count - kelvin_offset"
                if k
                else "counts are not temperature-linear; no conversion rule",
            },
            "software": {
                "name": "FLIR Research Interface",
                "version": __version__,
                "git_commit": _git_commit(),
                "python": sys.version.split()[0],
                "numpy": np.__version__,
                "zarr": zarr.__version__,
                "platform": platform.platform(),
            },
            "store": {
                "path": STORE_NAME,
                "zarr_format": 2,
                "chunk_frames": self._chunk,
                "compressor": str(self._compressor),
                "arrays": {
                    "counts": "uint16[time,y,x]",
                    "frame_id": "int64[time]",
                    "device_timestamp_ns": "int64[time]",
                    "host_timestamp_ns": "int64[time]",
                },
            },
        }
        (exp_dir / "metadata.json").write_text(json.dumps(meta, indent=2, default=str))

        self._group = zarr.open_group(str(exp_dir / STORE_NAME), mode="w")
        self._group.attrs["format_version"] = FORMAT_VERSION
        self._counts_arr = None  # created lazily on first frame (needs H, W)
        for nm in ("frame_id", "device_timestamp_ns", "host_timestamp_ns"):
            self._group.create_dataset(
                nm, shape=(0,), chunks=(max(self._chunk, 1024),), dtype="int64"
            )

        self._event("recording_started", {"name": name})
        with self._lock:
            self._state = RecorderState.RECORDING
        self._writer = threading.Thread(
            target=self._writer_loop, name="recorder-writer", daemon=True
        )
        self._writer.start()
        if self._service is not None and not self._listener_attached:
            self._service.add_listener(self.submit)
            self._listener_attached = True
        logger.info("recording to %s", exp_dir)
        return exp_dir

    def submit(self, frame: Frame) -> None:
        """Called on the camera thread. Never blocks."""
        if self._state != RecorderState.RECORDING:
            return
        with self._lock:
            self._frames_received += 1
        try:
            self._queue.put_nowait(frame)
            with self._lock:
                self._last_submitted_id = frame.frame_id
        except queue.Full:
            with self._lock:
                self._queue_dropped += 1
                if self._queue_dropped in (1, 10, 100, 1000):
                    logger.error(
                        "recording queue full: %d frames dropped so far", self._queue_dropped
                    )

    def stop(self) -> dict[str, Any]:
        """Finalize: drain queue, flush, write manifest. Returns the manifest."""
        if self._exp_dir is None:
            raise RuntimeError("not started")
        with self._lock:
            if self._state == RecorderState.RECORDING:
                self._state = RecorderState.FINALIZING
        self._pause.set()
        self._queue.put(None)  # sentinel; blocks only if queue is full of real frames, which drain
        if self._writer is not None:
            self._writer.join(timeout=60.0)
        self._flush()
        manifest = self._write_manifest()
        with self._lock:
            self._state = RecorderState.IDLE
        logger.info("recording finalized: %s", manifest)
        return manifest

    # -- test hooks ----------------------------------------------------------------------------

    def pause_writer_for_test(self) -> None:
        self._pause.clear()

    def resume_writer_for_test(self) -> None:
        self._pause.set()

    def flush_for_test(self) -> None:
        """Drain the queue and flush buffered frames synchronously (no finalization)."""
        deadline = time.monotonic() + 5.0
        while (self._queue.qsize() > 0 or self._buf) and time.monotonic() < deadline:
            time.sleep(0.01)
            with self._lock:
                pending = bool(self._buf)
            if pending and self._queue.qsize() == 0:
                self._flush()

    # -- writer thread -------------------------------------------------------------------------

    def _writer_loop(self) -> None:
        try:
            while True:
                self._pause.wait()
                try:
                    item = self._queue.get(timeout=0.25)
                except queue.Empty:
                    if self._buf:
                        self._flush()
                        self._check_free_space()
                    continue
                if item is None:
                    break
                self._account(item)
                if not self._buf:
                    self._buf_started = time.monotonic()
                self._buf.append(item)
                aged = self._buf_started is not None and (
                    time.monotonic() - self._buf_started >= self._flush_interval_s
                )
                if len(self._buf) >= self._chunk or aged:
                    self._flush()
                    self._check_free_space()
            self._flush()
        except Exception as exc:  # noqa: BLE001
            logger.exception("recorder writer failed")
            with self._lock:
                self._error = f"{type(exc).__name__}: {exc}"
                self._state = RecorderState.ERROR
            self._event("recording_error", {"error": self._error})

    def _check_free_space(self) -> None:
        limit = self._min_free_gb * 0.5
        free = self._free_space_gb(self._exp_dir or self._root)
        if free < limit:
            raise RuntimeError(
                f"free space {free:.2f} GB below {limit:.2f} GB during recording; stopped"
            )

    def _account(self, frame: Frame) -> None:
        with self._lock:
            if self._last_frame_id is not None and frame.frame_id > self._last_frame_id + 1:
                missing = frame.frame_id - self._last_frame_id - 1
                self._gap_events.append({"after_frame_id": self._last_frame_id, "missing": missing})
                self._events.append(
                    {
                        "t_utc": datetime.now(timezone.utc).isoformat(),
                        "type": "frame_gap",
                        "after_frame_id": self._last_frame_id,
                        "missing": missing,
                    }
                )
            self._last_frame_id = frame.frame_id
            if self._first_ts is None:
                self._first_ts = frame.device_timestamp_ns
            self._last_ts = frame.device_timestamp_ns

    def _flush(self) -> None:
        with self._lock:
            buf, self._buf = self._buf, []
            self._buf_started = None
        if not buf or self._group is None:
            return
        h, w = buf[0].counts.shape
        if self._counts_arr is None:
            self._counts_arr = self._group.create_dataset(
                "counts",
                shape=(0, h, w),
                chunks=(self._chunk, h, w),
                dtype="uint16",
                compressor=self._compressor,
            )
            self._counts_arr.attrs.update(
                {
                    "ir_format": buf[0].ir_format,
                    "pixel_format": buf[0].pixel_format,
                    "axes": ["time", "y", "x"],
                }
            )
        n0 = self._counts_arr.shape[0]
        n = len(buf)
        self._counts_arr.resize(n0 + n, h, w)
        self._counts_arr[n0 : n0 + n] = np.stack([f.counts for f in buf])
        for nm, key in (
            ("frame_id", "frame_id"),
            ("device_timestamp_ns", "device_timestamp_ns"),
            ("host_timestamp_ns", "host_timestamp_ns"),
        ):
            arr = self._group[nm]
            arr.resize(n0 + n)
            arr[n0 : n0 + n] = np.array([getattr(f, key) for f in buf], dtype="int64")
        with self._lock:
            self._frames_written += n

    def note_event(self, kind: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Append a timestamped event (NUC request, operator mark) to this recording's events.json.

        The id of the last frame accepted so far is stamped in as ``frame_id`` so playback can
        place the mark exactly; before the first frame there is no frame_id.
        """
        payload = dict(data or {})
        with self._lock:
            if self._last_submitted_id is not None and "frame_id" not in payload:
                payload["frame_id"] = self._last_submitted_id
        self._event(kind, payload)
        with self._lock:
            return dict(self._events[-1])

    def _event(self, kind: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._events.append(
                {"t_utc": datetime.now(timezone.utc).isoformat(), "type": kind, **data}
            )

    def _write_manifest(self) -> dict[str, Any]:
        assert self._exp_dir is not None
        self._event("recording_stopped", {})
        (self._exp_dir / "events.json").write_text(json.dumps(self._events, indent=2))
        with self._lock:
            gaps = sum(g["missing"] for g in self._gap_events)
            dur = (
                (self._last_ts - self._first_ts) / 1e9
                if self._first_ts is not None and self._last_ts
                else 0.0
            )
            manifest: dict[str, Any] = {
                "format_version": FORMAT_VERSION,
                "started_utc": self._started_at,
                "finished_utc": datetime.now(timezone.utc).isoformat(),
                "frames_received": self._frames_received,
                "frames_written": self._frames_written,
                "queue_dropped": self._queue_dropped,
                "frame_id_gaps": gaps,
                "gap_events": list(self._gap_events),
                "duration_s": dur,
                "error": self._error,
                "complete": self._error is None
                and self._queue_dropped == 0
                and self._frames_written == self._frames_received,
            }
        manifest["checksums"] = {
            "metadata.json": _sha256(self._exp_dir / "metadata.json"),
            "events.json": _sha256(self._exp_dir / "events.json"),
        }
        (self._exp_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        from flir_research_interface.analysis import preview as _preview

        try:
            manifest["previews"] = _preview.generate_previews(
                self._exp_dir
            )  # also rewrites manifest.json
        except Exception as exc:  # noqa: BLE001 - previews must never fail finalization
            logger.warning("%s: %s", type(exc).__name__, exc)
            manifest["previews"] = None
            _preview._atomic_write(
                self._exp_dir / "manifest.json", json.dumps(manifest, indent=2).encode()
            )
        return manifest


__all__ = ["FORMAT_VERSION", "STORE_NAME", "Recorder", "RecorderState", "inspect_experiment"]
