"""``/api/presets`` routes: thin handlers over :mod:`flir_research_interface.presets`.

Nothing here writes to the camera. The thermal part of a preset is checked against the connected
camera's ``enum_options`` / case count when there is one (and its info can be read), otherwise
only for unknown nodes and basic types.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from flir_research_interface import presets as store
from flir_research_interface.acquisition.service import AcquisitionService

logger = logging.getLogger(__name__)


class RenameRequest(BaseModel):
    new_name: str


class LastAppliedRequest(BaseModel):
    name: str | None = None


def make_presets_router(
    get_root: Callable[[], Path], get_service: Callable[[], AcquisitionService | None]
) -> APIRouter:
    """Build the router. ``get_root`` / ``get_service`` are read per request, so they follow a
    camera connecting and disconnecting."""
    router = APIRouter(prefix="/api/presets")

    async def _limits() -> tuple[dict[str, list[str]] | None, int | None]:
        svc = get_service()
        if svc is None:
            return None, None
        try:
            info = await run_in_threadpool(svc.backend.camera_info)
        except Exception:  # noqa: BLE001 - validation falls back to the camera-less checks
            logger.warning("camera info unavailable; validating without it", exc_info=True)
            return None, None
        return store.limits_from_camera_info(info)

    async def _run(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Run a store change, map its errors to HTTP statuses and return the whole document."""
        try:
            await run_in_threadpool(fn, get_root(), *args, **kwargs)
        except store.PresetNotFoundError as exc:
            raise HTTPException(404, f"no preset named {exc.args[0]!r}") from exc
        except store.PresetExistsError as exc:
            raise HTTPException(409, f"a preset named {exc.args[0]!r} already exists") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return await run_in_threadpool(store.load_presets, get_root())

    @router.get("")
    async def list_presets() -> dict[str, Any]:
        return await run_in_threadpool(store.load_presets, get_root())

    @router.get("/current-thermal")
    async def current_thermal() -> dict[str, Any]:
        """The connected camera's writable settings, for "save current as…"."""
        svc = get_service()
        if svc is None:
            raise HTTPException(409, "not connected")
        info = await run_in_threadpool(svc.backend.camera_info)
        values, left_out = store.thermal_from_camera_info(info)
        return {"thermal": values, "left_out": left_out}

    @router.post("/last-applied")
    async def last_applied(req: LastAppliedRequest) -> dict[str, Any]:
        return await _run(store.set_last_applied, req.name)

    @router.put("/{name}")
    async def put_preset(name: str, body: dict[str, Any]) -> dict[str, Any]:
        """Create or replace the preset ``name`` (the URL is the key)."""
        key = name.strip()
        if "name" in body and (not isinstance(body["name"], str) or body["name"].strip() != key):
            raise HTTPException(400, "the preset name in the body differs from the one in the URL")
        enum_options, n_cases = await _limits()
        return await _run(
            store.save_preset, {**body, "name": key}, enum_options=enum_options, n_cases=n_cases
        )

    @router.delete("/{name}")
    async def delete(name: str) -> dict[str, Any]:
        return await _run(store.delete_preset, name.strip())

    @router.post("/{name}/rename")
    async def rename(name: str, req: RenameRequest) -> dict[str, Any]:
        return await _run(store.rename_preset, name.strip(), req.new_name)

    return router


__all__ = ["make_presets_router"]
