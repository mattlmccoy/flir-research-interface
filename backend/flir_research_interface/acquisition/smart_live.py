"""Live smart ROI tracking on the camera stream.

``SmartLive.on_frame`` is an ``AcquisitionService`` listener: it runs on the camera thread for
every frame, converts counts to °C once, and steps one ``SmartTracker`` per smart ROI. Request
threads read the latest results (the TC-POWER feed, ``GET /api/live/roi-temps``) and the
per-frame overlays (the ``/ws/frames`` stream). The lock guards only dictionary swaps; tracker
work runs outside it, so a request thread never waits on detection and the camera thread never
waits on a request.

Live trackers get no per-ROI emissivity correction (``cam=None``), like every other live ROI.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
from typing import Any

from flir_research_interface.analysis.smart_roi import (
    SmartResult,
    SmartRoiSpec,
    SmartTracker,
    parse_smart_roi,
)
from flir_research_interface.analysis.smart_wire import smart_overlay
from flir_research_interface.camera.base import Frame
from flir_research_interface.radiometry.overrange import over_range_mask
from flir_research_interface.radiometry.temperature_linear import IRFormat, counts_to_celsius

logger = logging.getLogger(__name__)

FAIL_LOG_INTERVAL_S = 60.0  # a tracker that keeps failing: one-line warning at most this often


def _key(spec: SmartRoiSpec) -> SmartRoiSpec:
    """The part of a spec that changes tracking (a rename keeps the track)."""
    return dataclasses.replace(spec, name=None)


def _invalid(spec: SmartRoiSpec) -> SmartResult:
    """Searching, no temperatures: what the feed reports when this ROI could not be tracked."""
    none = {"mean_c": None, "max_c": None, "min_c": None}
    rings = [
        {"inner_px": a, "outer_px": b, **none}
        for a, b in zip((0, *spec.rings_px), spec.rings_px, strict=False)
    ]
    return SmartResult("searching", False, sample=dict(none), rings=rings)


class SmartLive:
    """Per-ROI live trackers. Thread-safe: one camera thread calls ``on_frame``; any thread may
    call ``set_rois``, ``latest``, ``overlays``, ``tracker`` and ``clear``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._specs: dict[int, SmartRoiSpec] = {}
        self._trackers: dict[int, SmartTracker] = {}
        self._broken: set[int] = set()  # specs whose tracker could not be built (logged once)
        self._results: dict[int, SmartResult] = {}
        # ROIs whose tracker is failing -> monotonic time of the last log line. Written by the
        # camera thread; set_rois/clear empty it (single dict ops, so no lock is needed).
        self._failing: dict[int, float] = {}

    # -- request threads -----------------------------------------------------------------------

    def set_rois(self, rois: list[dict[str, Any]]) -> None:
        """Adopt the live ROI set: keep trackers whose spec is unchanged, drop changed/removed ones
        (and their last result, so a stale outline is never reported for a new spec)."""
        specs: dict[int, SmartRoiSpec] = {}
        for raw in rois:
            if raw.get("kind") != "smart":
                continue
            try:
                spec = parse_smart_roi(raw)
            except (ValueError, TypeError) as exc:
                logger.warning("live smart ROI %r ignored: %s", raw.get("id"), exc)
                continue
            specs[spec.id] = spec
        with self._lock:
            for rid, old in self._specs.items():
                new = specs.get(rid)
                if new is not None and _key(new) == _key(old):
                    specs[rid] = old  # same tracking spec: keep the object so in-flight work lands
                    continue
                self._trackers.pop(rid, None)
                self._results.pop(rid, None)
                self._broken.discard(rid)
            self._specs = specs
            self._failing.clear()

    def latest(self) -> dict[int, SmartResult]:
        """The latest result per smart ROI id (absent until a frame has been tracked)."""
        with self._lock:
            return dict(self._results)

    def overlays(self) -> list[dict[str, Any]]:
        """The per-frame outline payloads for the frame stream (empty when nothing is tracked)."""
        results = self.latest()
        return [smart_overlay(results[rid], rid) for rid in sorted(results)]

    def tracker(self, roi_id: int) -> SmartTracker | None:
        with self._lock:
            return self._trackers.get(roi_id)

    def clear(self) -> None:
        """Forget every track and result (camera detached); the ROI specs are kept."""
        with self._lock:
            self._trackers.clear()
            self._results.clear()
            self._broken.clear()
            self._failing.clear()

    # -- camera thread ---------------------------------------------------------------------------

    def on_frame(self, frame: Frame) -> None:
        """Step every smart ROI's tracker on ``frame`` (listener; must never raise)."""
        with self._lock:
            specs = dict(self._specs)
            trackers = dict(self._trackers)
            broken = set(self._broken)
        if not specs:
            return
        h, w = frame.counts.shape[:2]
        try:
            celsius = counts_to_celsius(frame.counts, IRFormat(frame.ir_format))
        except ValueError:  # not a TemperatureLinear stream: nothing trustworthy to track
            self._store({rid: (trackers.get(rid), _invalid(s)) for rid, s in specs.items()},
                        specs, {}, frame.host_timestamp_ns)
            return
        over = over_range_mask(frame.counts)
        t_s = frame.host_timestamp_ns / 1e9
        built: dict[int, SmartTracker] = {}
        out: dict[int, tuple[SmartTracker | None, SmartResult]] = {}
        for rid, spec in specs.items():
            tr = trackers.get(rid)
            if tr is None or (tr.w, tr.h) != (w, h):
                if rid in broken:
                    out[rid] = (None, _invalid(spec))
                    continue
                try:
                    tr = SmartTracker(spec, w, h, cam=None)
                except Exception as exc:  # noqa: BLE001 - one bad spec must not stop the others
                    logger.warning("live smart ROI %d: tracker not built: %s", rid, exc)
                    self._mark_broken(rid, spec)
                    out[rid] = (None, _invalid(spec))
                    continue
                built[rid] = tr
            try:
                out[rid] = (tr, tr.update(celsius, t_s, over))
            except Exception:  # noqa: BLE001 - the feed reports this ROI invalid instead
                self._log_failure(rid, frame.frame_id)
                out[rid] = (tr, _invalid(spec))
            else:
                self._failing.pop(rid, None)
        self._store(out, specs, built, frame.host_timestamp_ns)

    def _log_failure(self, rid: int, frame_id: int) -> None:
        """Traceback on the first failure of a run of failures, then a one-line warning at most
        every ``FAIL_LOG_INTERVAL_S`` (the camera thread runs this every frame). Call only from
        inside an ``except`` block."""
        now = time.monotonic()
        last = self._failing.get(rid)
        if last is None:
            logger.exception("live smart ROI %d: tracker failed on frame %s", rid, frame_id)
        elif now - last >= FAIL_LOG_INTERVAL_S:
            logger.warning("live smart ROI %d: tracker still failing (frame %s)", rid, frame_id)
        else:
            return
        self._failing[rid] = now

    def _mark_broken(self, rid: int, spec: SmartRoiSpec) -> None:
        with self._lock:
            if self._specs.get(rid) is spec:
                self._broken.add(rid)

    def _store(
        self,
        out: dict[int, tuple[SmartTracker | None, SmartResult]],
        specs: dict[int, SmartRoiSpec],
        built: dict[int, SmartTracker],
        ts_ns: int,
    ) -> None:
        """Publish results, skipping any ROI whose spec changed while this frame was tracked."""
        with self._lock:
            for rid, (tr, res) in out.items():
                res.frame_ts_ns = ts_ns  # provenance: the feed refuses results older than its frame
                if self._specs.get(rid) is not specs[rid]:
                    continue  # set_rois replaced or removed it meanwhile: drop this frame's work
                if rid in built:
                    self._trackers[rid] = built[rid]
                elif tr is not None and self._trackers.get(rid) is not tr:
                    continue  # cleared meanwhile: start fresh next frame
                self._results[rid] = res


__all__ = ["SmartLive"]
