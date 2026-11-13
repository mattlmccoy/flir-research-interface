"""Auto-offload routes and the sweep that moves queued runs to the SSD (see ``offload.py``).

``register_offload_routes`` returns ``(queue, sweep)``: ``queue(run_dir)`` is called when a run
is finalized, ``sweep()`` moves whatever is ready. The sweep runs after each run's post-stop
exports, on a timer (``loop``), and on ``POST /api/storage/offload/retry``.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from flir_research_interface import offload

logger = logging.getLogger(__name__)

__all__ = ["register_offload_routes"]


class _EnabledBody(BaseModel):
    enabled: bool


Sweep = Callable[[], Awaitable[dict[str, Any]]]


def register_offload_routes(
    app: FastAPI,
    base: Callable[[], Path],
    drive: Callable[[], Path | None],
    idle: Callable[[], bool],
    run_busy: Callable[[Path], bool],
    move: Callable[[Path, Path], Awaitable[None]],
) -> tuple[Callable[[Path], None], Sweep]:
    """``drive()`` is the connected SSD's ``FLIR-recordings`` root (None when unplugged);
    ``idle()`` is False while recording, armed, finalizing or under closed-loop control;
    ``run_busy(dir)`` is True while that run's exports run; ``move(src, dst_parent)`` performs
    the verified move (raising on failure, the Mac copy intact)."""
    lock = asyncio.Lock()
    moving: set[tuple[str, str]] = set()

    def _state(e: dict[str, Any], d: Path | None, now: float) -> str:
        if (e["collection"], e["name"]) in moving:
            return "moving"
        src = base() / e["collection"] / e["name"]
        dst = d / e["collection"] / e["name"] if d is not None else None
        return offload.decide(
            e, now=now, drive=d is not None, idle=idle(), src_exists=src.is_dir(),
            dst_exists=dst is not None and dst.exists(), run_busy=run_busy(src),
        )

    def _doc() -> dict[str, Any]:
        doc = offload.load_offload(base())
        d, now = drive(), time.time()
        return {
            "enabled": doc["enabled"],
            "drive_connected": d is not None,
            "pending": [{**e, "state": _state(e, d, now)} for e in doc["pending"]],
        }

    def queue(run_dir: Path) -> None:
        """Queue a just-finalized run (``<base>/<collection>/<run>``) when offload is on and an
        SSD is registered (connected or not)."""
        b = base()
        if not offload.load_offload(b)["enabled"] or run_dir.parent.parent != b:
            return
        from flir_research_interface import storage

        if not storage.load_storage_config(b)["drive"]:
            return
        offload.queue_run(b, run_dir.parent.name, run_dir.name, now=time.time())

    async def sweep() -> dict[str, Any]:
        async with lock:
            b = base()
            doc = offload.load_offload(b)
            if doc["enabled"]:
                for e in doc["pending"]:
                    await _one(b, e)
        return _doc()

    async def _one(b: Path, e: dict[str, Any]) -> None:
        coll, name = e["collection"], e["name"]
        d = drive()
        action = _state(e, d, time.time())
        if action in ("done", "gone"):
            offload.finish(b, coll, name)
            return
        if action == "clash":
            offload.record_failure(
                b, coll, name, f"{coll}/{name} already exists on the SSD; both kept",
                now=time.time(), permanent=True)
            return
        if action != "move" or d is None:
            return
        moving.add((coll, name))
        try:
            await move(b / coll / name, d / coll)
            offload.finish(b, coll, name)
            logger.info("auto-offload moved %s/%s to the SSD", coll, name)
        except Exception as exc:  # noqa: BLE001 - the Mac copy is intact; retried later
            logger.warning("auto-offload of %s/%s failed: %s", coll, name, exc)
            offload.record_failure(b, coll, name, str(exc), now=time.time())
        finally:
            moving.discard((coll, name))

    @app.get("/api/storage/offload")
    def get_offload() -> dict[str, Any]:
        return _doc()

    @app.put("/api/storage/offload")
    async def put_offload(body: _EnabledBody) -> dict[str, Any]:
        offload.set_enabled(base(), body.enabled)
        return await sweep() if body.enabled else _doc()

    @app.post("/api/storage/offload/retry")
    async def retry_offload() -> dict[str, Any]:
        """Clear failure counts and try every queued run now."""
        offload.retry_all(base())
        return await sweep()

    return queue, sweep
