"""Smart ROI recorded-run routes: the full-rate compute job, its status, the plot series and the
per-frame playback overlays. Registered by ``create_app``.

Jobs follow the derived-export pattern: a progress record in ``app.state.smart_jobs`` (keyed by
run name and ROI id), work in the threadpool under the run's ``render_locks`` entry so it never
races a post-stop render, a regenerate or a move of the same run.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from flir_research_interface.analysis.smart_roi import SmartRoiSpec, parse_smart_roi
from flir_research_interface.analysis.smart_series import (
    compute_smart_series,
    load_smart_series,
    overlay_window,
    series_path,
    series_payload,
    stored_optics,
)
from flir_research_interface.playback.reader import ExperimentReader

logger = logging.getLogger(__name__)

_CACHE_MAX = 4  # loaded series kept for the overlay/plot polls (playback asks per frame window)


def stored_smart_specs(reader: ExperimentReader) -> list[SmartRoiSpec]:
    """The run's stored smart ROIs that parse (a bad one is logged and skipped)."""
    out: list[SmartRoiSpec] = []
    for raw in reader.metadata.get("rois") or []:
        if not isinstance(raw, dict) or raw.get("kind") != "smart":
            continue
        try:
            out.append(parse_smart_roi(raw))
        except (ValueError, TypeError) as exc:
            logger.warning("stored smart ROI %r ignored: %s", raw.get("id"), exc)
    return out


def _new_job(total: int = 0) -> dict[str, Any]:
    return {"state": "running", "done": 0, "total": total, "error": None}


def _run_job(job: dict[str, Any], reader: ExperimentReader, spec: SmartRoiSpec) -> None:
    def _cb(done: int, total: int) -> None:
        job["done"], job["total"] = done, total

    try:
        compute_smart_series(reader, spec, _cb)
        job["state"] = "done"
    except Exception as exc:  # noqa: BLE001 - surface the failure to the poller
        job["state"], job["error"] = "error", str(exc)
        logger.exception("smart ROI %d series failed for %s", spec.id, reader.path)


def compute_stored_smart_rois(app: FastAPI, exp_dir: Path) -> None:
    """Post-stop step (threadpool, caller holds the run's render lock): compute every stored
    smart ROI's series, publishing progress in ``app.state.smart_jobs``."""
    reader = ExperimentReader(exp_dir)
    for spec in stored_smart_specs(reader):
        job = _new_job(reader.n_frames)
        app.state.smart_jobs[(exp_dir.name, spec.id)] = job
        _run_job(job, reader, spec)


def register_smart_roi_routes(app: FastAPI, exp_dir: Callable[[str], Path]) -> None:
    app.state.smart_jobs = {}  # (run name, roi id) -> progress record
    cache: dict[Path, tuple[int, dict[str, Any]]] = {}
    cache_lock = threading.Lock()

    def _load(name: str, roi_id: int) -> dict[str, Any]:
        d = exp_dir(name)
        path = series_path(d, roi_id)
        try:
            mtime = path.stat().st_mtime_ns
        except FileNotFoundError:
            raise HTTPException(404, f"no smart ROI series for ROI {roi_id}; compute it") from None
        with cache_lock:
            hit = cache.get(path)
            if hit is not None and hit[0] == mtime:
                return hit[1]
        data = load_smart_series(d, roi_id)
        if data is None:
            raise HTTPException(404, f"no smart ROI series for ROI {roi_id}; compute it")
        with cache_lock:
            if len(cache) >= _CACHE_MAX:
                cache.clear()
            cache[path] = (mtime, data)
        return data

    def _spec(reader: ExperimentReader, roi_id: int) -> SmartRoiSpec:
        for raw in reader.metadata.get("rois") or []:
            if isinstance(raw, dict) and raw.get("id") == roi_id:
                if raw.get("kind") != "smart":
                    raise HTTPException(400, f"ROI {roi_id} is not a smart ROI")
                try:
                    return parse_smart_roi(raw)
                except ValueError as exc:
                    raise HTTPException(400, f"smart ROI {roi_id}: {exc}") from exc
        raise HTTPException(404, f"run has no ROI {roi_id}")

    @app.post("/api/experiments/{name}/smart-roi/{roi_id}/compute")
    async def smart_roi_compute(name: str, roi_id: int) -> dict[str, Any]:
        """Start (or return) the full-rate tracker job for a stored smart ROI; poll ``/status``.
        Pair with ``PUT /rois`` after editing the ROI in playback."""
        reader = ExperimentReader(exp_dir(name))
        spec = _spec(reader, roi_id)
        key = (name, roi_id)
        existing: dict[str, Any] | None = app.state.smart_jobs.get(key)
        if existing is not None and existing["state"] == "running":
            return existing
        job = _new_job(reader.n_frames)
        app.state.smart_jobs[key] = job

        async def _job() -> None:
            async with app.state.render_locks.get(name):
                await run_in_threadpool(_run_job, job, reader, spec)

        task = asyncio.create_task(_job())
        app.state.render_tasks.add(task)
        task.add_done_callback(app.state.render_tasks.discard)
        return job

    @app.get("/api/experiments/{name}/smart-roi/{roi_id}/status")
    def smart_roi_status(name: str, roi_id: int) -> dict[str, Any]:
        """``{state, done, total, error}``; ``done`` when a stored series exists (e.g. after a
        restart), ``idle`` when nothing was computed."""
        job: dict[str, Any] | None = app.state.smart_jobs.get((name, roi_id))
        if job is not None:
            return job
        data = load_smart_series(exp_dir(name), roi_id)
        if data is not None:
            n = int(data["n_frames"])
            return {"state": "done", "done": n, "total": n, "error": None}
        return {"state": "idle", "done": 0, "total": 0, "error": None}

    @app.get("/api/experiments/{name}/smart-roi/{roi_id}")
    def smart_roi_series(
        name: str, roi_id: int, max_points: int = Query(default=2000, ge=1, le=200_000)
    ) -> dict[str, Any]:
        """The stored per-frame series, downsampled to ``max_points`` for the plot (null gaps).
        ``stale`` is true when the run's ROI or frame count changed since it was computed."""
        data = _load(name, roi_id)
        out = series_payload(data, max_points)
        out["stale"] = _stale(name, roi_id, data)
        return out

    @app.get("/api/experiments/{name}/smart-roi/{roi_id}/overlay")
    def smart_roi_overlay(
        name: str,
        roi_id: int,
        start: int = Query(default=0, ge=0),
        count: int = Query(default=1, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        """Stored overlays for frame INDICES ``[start, start + count)`` (clipped to the run)."""
        return overlay_window(_load(name, roi_id), roi_id, start, count)

    def _stale(name: str, roi_id: int, data: dict[str, Any]) -> bool:
        reader = ExperimentReader(exp_dir(name))
        try:
            spec = _spec(reader, roi_id)
        except HTTPException:
            return True  # the ROI was removed or changed kind since
        now = {**dataclasses.asdict(spec), "search": [list(p) for p in spec.search],
               "rings_px": list(spec.rings_px)}
        then = dict(data.get("spec") or {})
        now.pop("name", None)
        then.pop("name", None)
        return (
            now != then
            or stored_optics(reader, roi_id) != data.get("optics")
            or reader.n_frames != len(data["state"])
        )


__all__ = ["compute_stored_smart_rois", "register_smart_roi_routes", "stored_smart_specs"]
