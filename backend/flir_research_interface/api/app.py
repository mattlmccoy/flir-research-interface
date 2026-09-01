"""FastAPI application: setup diagnostics, camera control, live frame WebSocket.

Milestone 3 scope: live view only (no recording). Binds to localhost by default; LAN exposure
and authentication are Milestone 10 concerns (brief §5).
"""

from __future__ import annotations

import asyncio
import logging
import platform
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from flir_research_interface import __version__
from flir_research_interface.acquisition.service import AcquisitionService, ServiceState
from flir_research_interface.api.frames import encode_frame_message
from flir_research_interface.camera import CAMERA_BACKENDS, create_backend
from flir_research_interface.camera.base import CameraBackend, CameraError, DeviceDescriptor
from flir_research_interface.camera.simulated import HotspotRampScene
from flir_research_interface.sdk_install import detect_and_select, pyspin_importable

logger = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


class ConnectRequest(BaseModel):
    backend: str = "simulated"
    serial: str | None = None


def _make_backend(name: str, *, sim_fps: float) -> CameraBackend:
    if name not in CAMERA_BACKENDS:
        raise HTTPException(400, f"unknown backend {name!r}; known: {sorted(CAMERA_BACKENDS)}")
    if name == "simulated":
        scene = HotspotRampScene(
            background_c=25.0,
            start_c=25.0,
            end_c=200.0,
            ramp_s=60.0,
            center_xy=(320, 240),
            radius_px=40,
        )
        return create_backend("simulated", scene=scene, fps=sim_fps, realtime=True)
    try:
        return create_backend(name)
    except CameraError as exc:
        raise HTTPException(400, str(exc)) from exc


def create_app(
    *, default_backend: str = "simulated", sim_fps: float = 30.0, viz_fps: float = 15.0
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        app.state.service = None
        app.state.backend_name = None
        yield
        svc: AcquisitionService | None = app.state.service
        if svc is not None:
            await run_in_threadpool(svc.disconnect)

    app = FastAPI(title="FLIR Research Interface", version=__version__, lifespan=lifespan)
    app.state.default_backend = default_backend
    app.state.sim_fps = sim_fps
    app.state.viz_fps = viz_fps

    def service() -> AcquisitionService | None:
        return app.state.service  # type: ignore[no-any-return]

    # -- health / setup --------------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__, "platform": platform.platform()}

    @app.get("/api/setup/sdk")
    def setup_sdk() -> dict[str, Any]:
        sel = detect_and_select()
        ok, detail = pyspin_importable()
        return {
            "system": sel.system,
            "machine": sel.machine,
            "python_tag": sel.python_tag,
            "supported": sel.supported,
            "reason": sel.reason,
            "sdk_artifact_hint": sel.sdk_artifact_hint,
            "pyspin_glob": sel.pyspin_glob,
            "pyspin_search_dirs": list(sel.pyspin_search_dirs),
            "sdk_local": sel.sdk_local,
            "pyspin_local": sel.pyspin_local,
            "steps": list(sel.steps),
            "pyspin_importable": ok,
            "pyspin_detail": detail,
        }

    @app.get("/api/setup/discovery")
    def setup_discovery() -> dict[str, Any]:
        from flir_research_interface.camera import gvcp

        out: dict[str, Any] = {"host_interfaces": [], "gvcp_devices": [], "spinnaker_devices": []}
        try:
            out["host_interfaces"] = [i.__dict__ for i in gvcp.host_interfaces()]
            for hit in gvcp.discover():
                d = hit.device
                entry = {
                    "via_interface": hit.interface.name,
                    "host_ip": f"{hit.interface.ip}/{hit.interface.netmask}",
                    "model": d.model,
                    "manufacturer": d.manufacturer,
                    "firmware": d.device_version,
                    "serial": d.serial,
                    "mac": d.mac,
                    "camera_ip": f"{d.current_ip}/{d.subnet_mask}",
                    "reachable_by_sdk": hit.reachable_by_sdk,
                    "fix": list(
                        gvcp.host_fix_commands(
                            d,
                            system=platform.system(),
                            interface=hit.interface.name,
                            service_name=hit.interface.service_name,
                        )
                    )
                    if not hit.reachable_by_sdk
                    else [],
                }
                out["gvcp_devices"].append(entry)
        except Exception as exc:  # noqa: BLE001
            out["gvcp_error"] = f"{type(exc).__name__}: {exc}"
        if "spinnaker" in CAMERA_BACKENDS:
            try:
                cam = create_backend("spinnaker")
                out["spinnaker_devices"] = [d.__dict__ for d in cam.enumerate()]
                cam.disconnect()
            except Exception as exc:  # noqa: BLE001
                out["spinnaker_error"] = f"{type(exc).__name__}: {exc}"
        return out

    # -- camera ----------------------------------------------------------------------------

    @app.get("/api/camera/devices")
    def devices(backend: str | None = None) -> list[dict[str, Any]]:
        name = backend or app.state.default_backend
        cam = _make_backend(name, sim_fps=app.state.sim_fps)
        try:
            return [d.__dict__ for d in cam.enumerate()]
        except CameraError as exc:
            raise HTTPException(500, str(exc)) from exc
        finally:
            cam.disconnect()

    @app.post("/api/camera/connect")
    async def connect(req: ConnectRequest) -> dict[str, Any]:
        if service() is not None:
            raise HTTPException(409, "already connected; disconnect first")
        cam = _make_backend(req.backend, sim_fps=app.state.sim_fps)
        try:
            devs = await run_in_threadpool(cam.enumerate)
            if not devs:
                raise HTTPException(404, "no camera found")
            chosen: DeviceDescriptor | None = next(
                (d for d in devs if req.serial is None or d.serial == req.serial), None
            )
            if chosen is None:
                raise HTTPException(404, f"no camera with serial {req.serial!r}")
            svc = AcquisitionService(cam)
            await run_in_threadpool(svc.connect, chosen)
            svc.start()
        except CameraError as exc:
            cam.disconnect()
            raise HTTPException(500, str(exc)) from exc
        except HTTPException:
            cam.disconnect()
            raise
        app.state.service = svc
        app.state.backend_name = req.backend
        return {"state": svc.state.value, "device": chosen.__dict__}

    @app.post("/api/camera/disconnect")
    async def disconnect() -> dict[str, Any]:
        svc = service()
        if svc is None:
            return {"state": ServiceState.DISCONNECTED.value}
        await run_in_threadpool(svc.disconnect)
        app.state.service = None
        app.state.backend_name = None
        return {"state": ServiceState.DISCONNECTED.value}

    @app.get("/api/camera/status")
    def status() -> dict[str, Any]:
        svc = service()
        if svc is None:
            return {"state": ServiceState.DISCONNECTED.value, "backend": None, "device": None}
        st = svc.stats()
        st["backend"] = app.state.backend_name
        st["device"] = svc.device.__dict__ if svc.device else None
        return st

    @app.get("/api/camera/info")
    async def info() -> dict[str, Any]:
        svc = service()
        if svc is None:
            raise HTTPException(409, "not connected")
        return await run_in_threadpool(svc.backend.camera_info)

    # -- live frames -----------------------------------------------------------------------

    @app.websocket("/ws/frames")
    async def ws_frames(ws: WebSocket) -> None:
        await ws.accept()
        min_interval = 1.0 / app.state.viz_fps if app.state.viz_fps > 0 else 0.0
        last_id: int | None = None
        last_sent = 0.0
        try:
            while True:
                svc = service()
                if svc is None or svc.state != ServiceState.ACQUIRING:
                    await ws.send_json(
                        {"type": "status", "state": svc.state.value if svc else "disconnected"}
                    )
                    await asyncio.sleep(0.5)
                    continue
                frame = await run_in_threadpool(svc.wait_for_frame, after_id=last_id, timeout_s=1.0)
                if frame is None:
                    await ws.send_json({"type": "status", **svc.stats()})
                    continue
                last_id = frame.frame_id
                now = time.monotonic()
                wait = min_interval - (now - last_sent)
                if wait > 0:
                    await asyncio.sleep(wait)
                last_sent = time.monotonic()
                await ws.send_bytes(encode_frame_message(frame, svc.stats()))
        except WebSocketDisconnect:
            return
        except Exception:  # noqa: BLE001
            logger.exception("websocket frame loop failed")
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass

    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")

    return app


__all__ = ["create_app"]
