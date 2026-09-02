"""FastAPI application: setup diagnostics, camera control, live frame WebSocket.

Milestone 3 scope: live view only (no recording). Binds to localhost by default; LAN exposure
and authentication are Milestone 10 concerns (brief §5).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import platform
import shutil
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from flir_research_interface import __version__
from flir_research_interface.acquisition.service import AcquisitionService, ServiceState
from flir_research_interface.api.frames import encode_frame_message
from flir_research_interface.api.reveal import Runner, contained, reveal
from flir_research_interface.camera import CAMERA_BACKENDS, create_backend
from flir_research_interface.camera.base import CameraBackend, CameraError, DeviceDescriptor
from flir_research_interface.camera.simulated import HotspotRampScene
from flir_research_interface.playback.reader import ExperimentReader, list_experiments
from flir_research_interface.recording.recorder import Recorder, RecorderState
from flir_research_interface.sdk_install import detect_and_select, pyspin_importable

logger = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


class ConnectRequest(BaseModel):
    backend: str = "simulated"
    serial: str | None = None


class RecordingStartRequest(BaseModel):
    name: str
    metadata: dict[str, Any] = {}
    visible: bool = False


class ParametersRequest(BaseModel):
    values: dict[str, Any]


class EventRequest(BaseModel):
    name: str
    note: str | None = None


class MetadataPatch(BaseModel):
    experiment: Any


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
    *,
    default_backend: str = "simulated",
    sim_fps: float = 30.0,
    viz_fps: float = 15.0,
    experiments_root: Path | None = None,
    min_free_gb: float = 2.0,
    reveal_runner: Runner | None = None,
    visible_factory: Callable[[], Any] | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        app.state.service = None
        app.state.backend_name = None
        app.state.recorder = None
        app.state.visible = None
        yield
        await _finalize_recording()
        svc: AcquisitionService | None = app.state.service
        if svc is not None:
            await run_in_threadpool(svc.disconnect)

    app = FastAPI(title="FLIR Research Interface", version=__version__, lifespan=lifespan)
    app.state.default_backend = default_backend
    app.state.sim_fps = sim_fps
    app.state.viz_fps = viz_fps
    app.state.experiments_root = Path(experiments_root) if experiments_root else Path("experiments")
    app.state.min_free_gb = min_free_gb
    app.state.reveal_runner = reveal_runner

    def service() -> AcquisitionService | None:
        return app.state.service  # type: ignore[no-any-return]

    def recorder() -> Recorder | None:
        return app.state.recorder  # type: ignore[no-any-return]

    def _visible_status() -> dict[str, Any]:
        vis = app.state.visible
        if vis is not None:
            return vis.stats()  # type: ignore[no-any-return]
        if visible_factory is None:
            return {"state": "unavailable", "reason": "ffmpeg or RTSP credentials not configured"}
        return {"state": "idle"}

    async def _finalize_recording() -> dict[str, Any] | None:
        # Thermal data first (the science record), then the visible video; the visible stop may
        # wait on ffmpeg and must never delay or endanger the manifest.
        rec = recorder()
        manifest = None
        if rec is not None:
            if rec.state in (RecorderState.RECORDING, RecorderState.ERROR):
                manifest = await run_in_threadpool(rec.stop)
            app.state.recorder = None
        vis = app.state.visible
        if vis is not None:
            app.state.visible = None
            try:
                visible_info = await run_in_threadpool(vis.stop)
            except Exception as exc:  # noqa: BLE001 - report, never raise past the thermal finalize
                logger.exception("visible recorder stop failed")
                visible_info = {"state": "error", "error": str(exc)}
            if manifest is not None:
                manifest["visible"] = visible_info
        return manifest

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
        await _finalize_recording()  # never lose a recording because the operator disconnected
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

    @app.post("/api/camera/parameters")
    async def camera_parameters(req: ParametersRequest) -> dict[str, Any]:
        """Write object parameters / case / NUC mode / frame rate. Locked while recording (§30)."""
        svc = service()
        if svc is None:
            raise HTTPException(409, "not connected")
        rec = recorder()
        if rec is not None and rec.state == RecorderState.RECORDING:
            raise HTTPException(409, "camera parameters are locked while recording")
        try:
            applied = await run_in_threadpool(svc.backend.set_parameters, req.values)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except CameraError as exc:
            raise HTTPException(500, str(exc)) from exc
        return {"applied": applied}

    @app.post("/api/camera/nuc")
    async def camera_nuc() -> dict[str, Any]:
        """Trigger a NUC now. Allowed during recording; the request is logged as an event."""
        svc = service()
        if svc is None:
            raise HTTPException(409, "not connected")
        try:
            await run_in_threadpool(svc.backend.execute, "NUCAction")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except CameraError as exc:
            raise HTTPException(500, str(exc)) from exc
        rec = recorder()
        if rec is not None and rec.state == RecorderState.RECORDING:
            rec.note_event("nuc", {"source": "operator"})
        return {"ok": True}

    # -- recording -------------------------------------------------------------------------

    @app.post("/api/recording/start")
    async def recording_start(req: RecordingStartRequest) -> dict[str, Any]:
        svc = service()
        if svc is None or svc.state != ServiceState.ACQUIRING:
            raise HTTPException(409, "camera is not acquiring")
        if recorder() is not None and recorder().state == RecorderState.RECORDING:  # type: ignore[union-attr]
            raise HTTPException(409, "already recording")
        rec = Recorder(
            svc, experiments_root=app.state.experiments_root, min_free_gb=app.state.min_free_gb
        )
        try:
            exp_dir = await run_in_threadpool(rec.start, name=req.name, metadata=req.metadata)
        except RuntimeError as exc:
            raise HTTPException(507 if "free space" in str(exc) else 400, str(exc)) from exc
        app.state.recorder = rec
        visible: dict[str, Any] = {"state": "idle"}
        if req.visible:
            if visible_factory is None:
                visible = _visible_status()
            else:
                vis = visible_factory()
                try:
                    visible = await run_in_threadpool(vis.start, exp_dir)
                    app.state.visible = vis
                except Exception as exc:  # noqa: BLE001 - the thermal recording must proceed
                    logger.exception("visible recorder failed to start")
                    visible = {"state": "error", "error": str(exc)}
                    rec.note_event("visible_error", {"error": str(exc)})
        return {"state": rec.state.value, "experiment_dir": str(exp_dir), "visible": visible}

    @app.post("/api/recording/stop")
    async def recording_stop() -> dict[str, Any]:
        rec = recorder()
        if rec is None:
            raise HTTPException(409, "not recording")
        manifest = await _finalize_recording()
        return manifest or {"state": RecorderState.IDLE.value}

    @app.post("/api/recording/event")
    def recording_event(req: EventRequest) -> dict[str, Any]:
        """Operator mark (RF ON/OFF, note…) stamped with the last recorded frame id (§ M8)."""
        rec = recorder()
        if rec is None or rec.state != RecorderState.RECORDING:
            raise HTTPException(409, "not recording")
        name = req.name.strip()
        if not name:
            raise HTTPException(400, "event name is required")
        data: dict[str, Any] = {"name": name}
        if req.note:
            data["note"] = req.note
        return rec.note_event("annotation", data)

    @app.get("/api/recording/status")
    def recording_status() -> dict[str, Any]:
        rec = recorder()
        root: Path = app.state.experiments_root
        if rec is None:
            probe = root if root.exists() else root.parent
            free = shutil.disk_usage(probe).free / 1e9 if probe.exists() else None
            return {
                "state": RecorderState.IDLE.value,
                "experiments_root": str(root),
                "free_space_gb": free,
                "min_free_gb": app.state.min_free_gb,
                "visible": _visible_status(),
            }
        st = rec.stats()
        st["visible"] = _visible_status()
        return st

    @app.get("/api/experiments")
    def experiments() -> list[dict[str, Any]]:
        return list_experiments(app.state.experiments_root)

    def _exp_dir(name: str) -> Path:
        root: Path = app.state.experiments_root
        if "/" in name or "\\" in name or name in ("", ".", ".."):
            raise HTTPException(400, "invalid experiment name")
        d = root / name
        if not d.is_dir():
            raise HTTPException(404, f"experiment {name!r} not found")
        if not contained(root, d):
            raise HTTPException(400, "experiment path is outside the experiments root")
        return d

    def _open(name: str) -> ExperimentReader:
        d = _exp_dir(name)
        try:
            return ExperimentReader(d)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            raise HTTPException(404, f"experiment {name!r} is not readable: {exc}") from exc

    def _reveal(path: Path) -> dict[str, Any]:
        root: Path = app.state.experiments_root
        if not contained(root, path):
            raise HTTPException(400, "path is outside the experiments root")
        res = reveal(path.resolve(), runner=app.state.reveal_runner)
        if not res["ok"] and "no file manager" in res.get("error", ""):
            raise HTTPException(501, res["error"])
        return res

    @app.post("/api/experiments/reveal-root")
    def reveal_root() -> dict[str, Any]:
        root: Path = app.state.experiments_root
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HTTPException(500, f"cannot create experiments root: {exc}") from exc
        return _reveal(root)

    @app.post("/api/experiments/{name}/reveal")
    def reveal_experiment(name: str) -> dict[str, Any]:
        return _reveal(_exp_dir(name))

    @app.get("/api/experiments/{name}")
    def experiment_info(name: str) -> dict[str, Any]:
        r = _open(name)
        info = r.info()
        info["events"] = r.events
        return info

    @app.get("/api/experiments/{name}/timeline")
    def experiment_timeline(name: str) -> dict[str, list[Any]]:
        return _open(name).timeline()

    @app.patch("/api/experiments/{name}/metadata")
    def experiment_metadata_patch(name: str, req: MetadataPatch) -> dict[str, Any]:
        """Edit operator fields after the fact; camera/conversion blocks stay as recorded."""
        from flir_research_interface.recording.metadata import patch_experiment_metadata

        if not isinstance(req.experiment, dict):
            raise HTTPException(400, "experiment must be an object of field: value")
        d = _exp_dir(name)
        try:
            return patch_experiment_metadata(d, req.experiment)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/experiments/{name}/series")
    async def experiment_series(name: str, rois: str) -> dict[str, Any]:
        """ROI values on every frame of a recording (spots: value; rects: min/max/mean)."""
        from flir_research_interface.analysis.series import parse_rois, roi_series

        try:
            parsed = parse_rois(rois)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        r = _open(name)
        out = await run_in_threadpool(roi_series, r, parsed)
        out["events"] = r.events
        return out

    @app.get("/api/experiments/{name}/frames/{index}")
    def experiment_frame(name: str, index: int) -> Response:
        r = _open(name)
        try:
            frame = r.frame(index)
        except IndexError as exc:
            raise HTTPException(404, str(exc)) from exc
        payload = encode_frame_message(
            frame,
            extra={
                "index": index,
                "n_frames": r.n_frames,
                "t_s": r.t_s(index),
                "source": "playback",
            },
        )
        return Response(content=payload, media_type="application/octet-stream")

    # -- exports (Milestone 7) ---------------------------------------------------------------

    def _download(data: bytes | str, media_type: str, filename: str) -> Response:
        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/experiments/{name}/export/series.csv")
    async def export_series_csv(name: str, rois: str) -> Response:
        from flir_research_interface.analysis.export import series_csv
        from flir_research_interface.analysis.series import parse_rois

        try:
            parsed = parse_rois(rois)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        r = _open(name)
        text = await run_in_threadpool(series_csv, r, parsed)
        return _download(text, "text/csv", f"{r.path.name}_series.csv")

    @app.get("/api/experiments/{name}/frames/{index}/export")
    async def export_frame(name: str, index: int, format: str = "csv") -> Response:
        from flir_research_interface.analysis.export import frame_bytes

        r = _open(name)
        try:
            data, media, filename = await run_in_threadpool(frame_bytes, r, index, format)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except IndexError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _download(data, media, filename)

    @app.post("/api/experiments/{name}/export/hdf5")
    async def export_hdf5_route(name: str) -> dict[str, Any]:
        from flir_research_interface.analysis.export import export_hdf5

        return await run_in_threadpool(export_hdf5, _open(name))

    def _png_response(path: Path, request: Request) -> Response:
        if not path.is_file():
            raise HTTPException(404, f"{path.name} not generated yet")
        data = path.read_bytes()
        etag = f'"{hashlib.sha256(data).hexdigest()}"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        return Response(
            content=data,
            media_type="image/png",
            headers={"Cache-Control": "no-cache", "ETag": etag},
        )

    @app.get("/api/experiments/{name}/preview.png")
    def experiment_preview(name: str, request: Request) -> Response:
        return _png_response(_exp_dir(name) / "preview.png", request)

    @app.get("/api/experiments/{name}/keyframes.png")
    def experiment_keyframes(name: str, request: Request) -> Response:
        return _png_response(_exp_dir(name) / "keyframes.png", request)

    @app.post("/api/experiments/{name}/previews")
    async def experiment_regenerate_previews(name: str) -> dict[str, Any]:
        from flir_research_interface.analysis.preview import generate_previews

        r = _open(name)
        try:
            return await run_in_threadpool(generate_previews, r.path)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

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
