"""M11: the armed-recording controller that sits between the camera thread and the recorder.

``Armer`` listens to every frame on the acquisition thread, evaluates the watched ROI statistic,
feeds the ``TriggerMachine`` and keeps a pre-trigger ring buffer. It never does I/O on the camera
thread: when the machine says *start* it raises a flag; the API's arm loop creates the recorder
(disk I/O in a worker), then ``attach`` flushes the ring and forwards live frames in order under
one lock so the store never sees frames out of order. *Stop* is likewise flagged and finalised by
the API. ``watched_value`` is the single evaluation rule (shared with nothing else on purpose: it
must be fast, one ROI per frame).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

import numpy as np

from flir_research_interface.analysis.series import roi_index
from flir_research_interface.camera.base import Frame
from flir_research_interface.radiometry.temperature_linear import IRFormat, counts_to_celsius
from flir_research_interface.recording.recorder import Recorder
from flir_research_interface.recording.trigger import TriggerMachine, TriggerSpec


def watched_value(frame: Frame, roi: dict[str, Any] | None, stat: str) -> float | None:
    """The ROI statistic (°C) on one frame, or None when it cannot be evaluated."""
    if roi is None:
        return None
    try:
        fmt = IRFormat(frame.ir_format)
    except ValueError:
        return None
    if fmt is IRFormat.RADIOMETRIC:
        return None
    h, w = frame.counts.shape
    if roi["kind"] == "spot":
        x, y = int(roi["x"]), int(roi["y"])
        if not (0 <= x < w and 0 <= y < h):
            return None
        return float(counts_to_celsius(frame.counts[y : y + 1, x : x + 1], fmt)[0, 0])
    if roi["kind"] == "rect":
        x0, y0 = max(0, int(roi["x0"])), max(0, int(roi["y0"]))
        x1, y1 = min(w, int(roi["x1"])), min(h, int(roi["y1"]))
        if x1 <= x0 or y1 <= y0:
            return None
        vals = counts_to_celsius(frame.counts[y0:y1, x0:x1], fmt)
    else:
        ys, xs = roi_index(roi, w, h)
        if len(ys) == 0:
            return None
        vals = counts_to_celsius(frame.counts[ys, xs], fmt)
    if stat == "max":
        return float(np.nanmax(vals))
    if stat == "min":
        return float(np.nanmin(vals))
    return float(np.nanmean(vals))


class Armer:
    def __init__(
        self,
        spec: TriggerSpec,
        rois: list[dict[str, Any]],
        *,
        fps_hint: float = 30.0,
        clock: Any = time.monotonic,
    ) -> None:
        self.spec = spec
        self.machine = TriggerMachine(spec)
        self._clock = clock
        self._lock = threading.Lock()
        by_id = {r["id"]: r for r in rois}
        self._start_roi = by_id.get(spec.start.roi) if spec.start.roi is not None else None
        self._end_roi = by_id.get(spec.end.roi) if spec.end.roi is not None else None
        if self._start_roi is None and rois and spec.start.kind == "threshold":
            self._start_roi = rois[0]
        if self._end_roi is None and spec.end.kind == "threshold":
            self._end_roi = self._start_roi or (rois[0] if rois else None)
        n_ring = max(1, int(spec.pretrigger_s * fps_hint) + 2)
        self._ring: deque[Frame] = deque(maxlen=n_ring)
        self._rec: Recorder | None = None
        self._index = 0
        self.pending: str | None = None  # "start" | "stop" raised for the arm loop
        self.last_value: float | None = None
        self.pretrigger_frames = 0
        self.started_frame_id: int | None = None
        self.ended_frame_id: int | None = None

    # -- camera thread -------------------------------------------------------------------------

    def on_frame(self, frame: Frame) -> None:
        with self._lock:
            state = self.machine.state
            roi = self._start_roi if state == "armed" else self._end_roi
            stat = self.spec.start.stat if state == "armed" else self.spec.end.stat
            value = watched_value(frame, roi, stat) if roi is not None else None
            self.last_value = value
            action = self.machine.feed(self._clock(), self._index, value)
            self._index += 1
            if self._rec is not None:
                self._rec.submit(frame)
            else:
                self._ring.append(frame)  # armed, or start pending: keep buffering
            if action == "start":
                self.started_frame_id = frame.frame_id
                self.pending = "start"
            elif action == "stop":
                self.ended_frame_id = frame.frame_id
                self.pending = "stop"

    # -- API side ----------------------------------------------------------------------------

    def manual_start(self) -> bool:
        with self._lock:
            if self.machine.state != "armed":
                return False
            self.machine.start(self._clock(), self._index)
            self.pending = "start"
            return True

    def attach(self, rec: Recorder) -> int:
        """Flush the ring (pre-trigger frames + frames that arrived while starting) then forward
        live frames. Returns the number of pre-trigger frames written."""
        with self._lock:
            pre = 0
            for f in self._ring:
                if self.started_frame_id is not None and f.frame_id < self.started_frame_id:
                    pre += 1
                rec.submit(f)
            self._ring.clear()
            self._rec = rec
            self.pretrigger_frames = pre
            if self.pending == "start":
                self.pending = None
            return pre

    def take_pending(self) -> str | None:
        with self._lock:
            p, self.pending = self.pending, None
            return p

    def detach(self) -> Recorder | None:
        with self._lock:
            rec, self._rec = self._rec, None
            return rec

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "trigger": self.spec.as_dict(),
                "machine": self.machine.status(),
                "watched_value": self.last_value,
                "watched_roi": (self._start_roi or {}).get("id"),
                "ring_frames": len(self._ring),
                "pretrigger_frames": self.pretrigger_frames,
            }


__all__ = ["Armer", "watched_value"]
