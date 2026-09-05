"""FastAPI application: setup diagnostics, camera control, live frame WebSocket.

Milestone 3 scope: live view only (no recording). Binds to localhost by default; LAN exposure
and authentication are Milestone 10 concerns (brief §5).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import platform
import shutil
import struct
import sys
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from flir_research_interface import __version__, storage
from flir_research_interface.acquisition.service import AcquisitionService, ServiceState
from flir_research_interface.api.frames import encode_frame_message
from flir_research_interface.api.reveal import Runner, contained, reveal
from flir_research_interface.camera import CAMERA_BACKENDS, create_backend
from flir_research_interface.camera.base import CameraBackend, CameraError, DeviceDescriptor, Frame
from flir_research_interface.camera.simulated import HotspotRampScene
from flir_research_interface.concurrency import KeyedLocks
from flir_research_interface.playback.reader import ExperimentReader, list_experiments
from flir_research_interface.recording.recorder import Recorder, RecorderState
from flir_research_interface.sdk_install import detect_and_select, pyspin_importable

logger = logging.getLogger(__name__)

API_VERSION = "1.0"
"""Handshake version for the site UI (spec §6.3): major mismatch = refuse, minor = banner."""
LOCAL_ORIGIN_RE = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
CLIENT_HEADER = "x-fri-client"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def install_cross_origin_policy(app: FastAPI, *, site_origin: str | None) -> None:
    """CORS for localhost + the site, Private Network Access, and the X-FRI-Client requirement.

    A state-changing request whose ``Origin`` differs from the operator's own host (i.e. the UI
    served from the site, or any other website) must carry ``X-FRI-Client: 1``; the operator-served
    UI (same origin) and local tools without an ``Origin`` header are unaffected.
    """
    from starlette.middleware.cors import CORSMiddleware
    from starlette.requests import Request as StarletteRequest
    from starlette.responses import JSONResponse

    def _cross_origin(request: StarletteRequest) -> bool:
        origin = request.headers.get("origin")
        if not origin:
            return False
        host = request.headers.get("host", "")
        return origin.split("://", 1)[-1].lower() != host.lower()

    @app.middleware("http")
    async def _client_header_guard(request: StarletteRequest, call_next):  # type: ignore[no-untyped-def]
        if (
            request.method not in SAFE_METHODS
            and request.url.path.startswith("/api/")
            and _cross_origin(request)
            and request.headers.get(CLIENT_HEADER) != "1"
        ):
            return JSONResponse(
                {"detail": "browser requests must send the X-FRI-Client: 1 header"},
                status_code=403,
            )
        response = await call_next(request)
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[site_origin] if site_origin else [],
        allow_origin_regex=LOCAL_ORIGIN_RE,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["content-type", CLIENT_HEADER, "if-none-match"],
        expose_headers=["etag", "content-disposition"],
        allow_private_network=True,  # Chrome Local Network Access preflight
        max_age=600,
    )


FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


class ConnectRequest(BaseModel):
    backend: str = "simulated"
    serial: str | None = None


class RecordingStartRequest(BaseModel):
    name: str
    metadata: dict[str, Any] = {}
    visible: bool = False
    rois: list[dict[str, Any]] | None = None
    # NUC right before the recording, then NUCMode=Off until stop so the camera never freezes
    # mid-run (the A70 repeats its image for ~2 s during a NUC); the previous mode is restored.
    nuc_hold: bool = True
    # Periodic (time-lapse) recording: keep every Nth frame (1 = every frame).
    every_nth: int = Field(default=1, ge=1, le=100000)


class FrameRangeRequest(BaseModel):
    start: int = 0
    stop: int
    step: int = 1
    format: str = "csv"


class ArmRequest(RecordingStartRequest):
    trigger: dict[str, Any] = {}


class ParametersRequest(BaseModel):
    values: dict[str, Any]


class EventRequest(BaseModel):
    name: str
    note: str | None = None


class MetadataPatch(BaseModel):
    experiment: Any


class RoisRequest(BaseModel):
    rois: list[dict[str, Any]]


class MediaRequest(BaseModel):
    start: int = 0
    stop: int = 0
    step: int = Field(default=1, ge=1, le=1000)
    scale: int = Field(default=2, ge=1, le=4)
    speed: float = Field(default=1.0, gt=0, le=60)
    fps: float | None = None
    fmt: str = "mp4"
    with_rois: bool = True
    frame_stats: bool = False
    timestamp: bool = True
    colorbar: bool = True
    title: str | None = None
    plot_roi: int | None = None  # legacy single-ROI live plot
    plot_rois: list[int] = Field(default_factory=list)  # legacy: same stats for every ROI
    plot_stat: str = "mean"  # legacy single stat
    plot_stats: list[str] = Field(default_factory=list)  # legacy: stats for every plot_roi
    plot_series: list[str] = Field(default_factory=list)  # per-ROI lines as "<roi_id>:<stat>"
    overlay_rois: list[int] = Field(default_factory=list)  # ROI boxes to draw ([]=all)
    visible_opacity: float = Field(default=0.0, ge=0.0, le=1.0)  # blend visible camera (0 = off)
    palette: str = "inferno"  # colour palette for the thermal frame
    rois: list[dict[str, Any]] | None = None  # when given, persist first (on-screen ROIs)


def _parse_series(items: list[str]) -> tuple[tuple[int, str], ...]:
    """Parse "<roi_id>:<stat>" strings into (id, stat) pairs, skipping malformed ones."""
    out: list[tuple[int, str]] = []
    for it in items:
        rid, _, stat = it.partition(":")
        if stat and rid.strip().lstrip("-").isdigit():
            out.append((int(rid), stat))
    return tuple(out)


class RegisterDriveRequest(BaseModel):
    mount: str


class MoveRequest(BaseModel):
    to: str  # "drive" | "local"


class ForceIpRequest(BaseModel):
    mac: str
    ip: str
    subnet_mask: str
    gateway: str = "0.0.0.0"


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
    site_origin: str | None = None,
    preview_factory: Callable[[], Any] | None = None,
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
    install_cross_origin_policy(app, site_origin=site_origin)
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

    def _export_roi_series(exp_dir: Path) -> None:
        """Write exports/roi_series.csv for the ROIs stored with the recording (if any)."""
        from flir_research_interface.analysis.export import series_csv

        reader = ExperimentReader(exp_dir)
        rois = reader.metadata.get("rois")
        if not rois or reader.n_frames == 0:
            return
        out_dir = exp_dir / "exports"
        out_dir.mkdir(exist_ok=True)
        (out_dir / "roi_series.csv").write_text(series_csv(reader, rois))
        logger.info("wrote %s", out_dir / "roi_series.csv")

    def _write_run_summary(exp_dir: Path) -> None:
        """README.txt + exports/roi_plot.png + peak_frame(.png|_rois.png), derived, regenerable."""
        from flir_research_interface.analysis.annotate import write_annotated_frames
        from flir_research_interface.analysis.run_summary import write_run_summary

        reader = ExperimentReader(exp_dir)
        logger.info("run summary: %s", write_run_summary(reader))
        if reader.n_frames:
            logger.info("peak frames: %s", write_annotated_frames(reader))

    app.state.render_tasks = set()
    app.state.derived_jobs = {}  # experiment name -> progress record for on-demand regenerate
    app.state.move_jobs = {}  # experiment name -> progress record for an offload/restore move
    app.state.media_jobs = {}  # experiment name -> progress record for a media-export render
    # one lock per experiment so the post-stop auto-render and an on-demand regenerate never write
    # that run's thermal-video files at the same time
    app.state.render_locks = KeyedLocks()

    def _render_thermal_video(exp_dir: Path) -> None:
        """exports/thermal_preview.mp4 (clean) and thermal_preview_rois.mp4 (ROIs drawn)."""
        from flir_research_interface.analysis.thermal_video import render_thermal_video

        reader = ExperimentReader(exp_dir)
        render_thermal_video(reader)
        if reader.metadata.get("rois"):
            render_thermal_video(reader, with_rois=True)

    def _schedule_thermal_video(exp_dir: Path) -> None:
        """Render after stop without holding the stop: an encode of a long run takes seconds."""

        async def _job() -> None:
            try:
                async with app.state.render_locks.get(exp_dir.name):
                    await run_in_threadpool(_render_thermal_video, exp_dir)
            except Exception:  # noqa: BLE001 - a convenience file must never surface as an error
                logger.exception("thermal preview video render failed for %s", exp_dir)

        task = asyncio.create_task(_job())
        app.state.render_tasks.add(task)
        task.add_done_callback(app.state.render_tasks.discard)

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
            exp_dir = rec.experiment_dir
            if rec.state in (RecorderState.RECORDING, RecorderState.ERROR):
                svc_now = service()
                if svc_now is not None and rec.state == RecorderState.RECORDING:
                    try:  # camera housekeeping at stop: FPA/housing temperature explains drift
                        info_now = await run_in_threadpool(svc_now.backend.camera_info)
                        rec.note_event(
                            "camera_state",
                            {
                                "when": "stop",
                                "device_temperature_c": info_now.get("device_temperature_c"),
                                "nuc_count": info_now.get("nuc_count"),
                            },
                        )
                    except Exception:  # noqa: BLE001 - never delay or endanger the stop
                        logger.debug("camera_state at stop unavailable", exc_info=True)
                manifest = await run_in_threadpool(rec.stop)
            app.state.recorder = None
            _nuc_hold_end()
            if manifest is not None and exp_dir is not None:
                try:
                    await run_in_threadpool(_export_roi_series, exp_dir)
                except Exception:  # noqa: BLE001 - a convenience file must never fail the finalize
                    logger.exception("automatic ROI series export failed")
                try:
                    await run_in_threadpool(_write_run_summary, exp_dir)
                except Exception:  # noqa: BLE001 - a convenience file must never fail the finalize
                    logger.exception("run summary failed")
                _schedule_thermal_video(exp_dir)
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
        return {
            "status": "ok",
            "version": __version__,
            "app_version": __version__,
            "api_version": API_VERSION,
            "platform": platform.platform(),
        }

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
                    **gvcp.diagnose(hit),
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

    @app.post("/api/setup/force-ip")
    def setup_force_ip(req: ForceIpRequest) -> dict[str, Any]:
        """GigE Vision FORCEIP: give the camera (by MAC) a temporary address until it reboots."""
        from flir_research_interface.camera import gvcp

        hit = next((h for h in gvcp.discover() if h.device.mac.lower() == req.mac.lower()), None)
        if hit is None:
            raise HTTPException(404, f"no camera with MAC {req.mac} answered discovery")
        try:
            acked = gvcp.force_ip(hit, req.ip, req.subnet_mask, req.gateway)
        except (OSError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        after = next((h for h in gvcp.discover() if h.device.mac.lower() == req.mac.lower()), None)
        return {
            "acked": acked,
            "camera_ip": f"{after.device.current_ip}/{after.device.subnet_mask}" if after else None,
            "reachable_by_sdk": after.reachable_by_sdk if after else False,
        }

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

    @app.get("/api/calibration/visible")
    def get_visible_alignment() -> dict[str, Any]:
        from flir_research_interface.analysis.calibration import load_alignment

        doc = load_alignment(app.state.experiments_root)
        if doc is None:
            raise HTTPException(404, "no visible alignment stored yet")
        return doc

    @app.put("/api/calibration/visible")
    async def put_visible_alignment(request: Request) -> dict[str, Any]:
        """Store the browser-fitted visible→IR homography for every client and future recordings."""
        from flir_research_interface.analysis.calibration import save_alignment

        try:
            body = await request.json()
            return await run_in_threadpool(save_alignment, app.state.experiments_root, body)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/profile/suggest")
    def profile_suggest(q: str = "") -> dict[str, Any]:
        """Offline profile builder: fields + marks suggested for a free-text description."""
        from flir_research_interface.analysis.profile_library import suggest

        return suggest(q[:500])

    @app.get("/api/profile")
    def get_profile() -> dict[str, Any]:
        from flir_research_interface.analysis.profile import load_profile

        return load_profile(app.state.experiments_root)

    @app.put("/api/profile")
    async def put_profile(request: Request) -> dict[str, Any]:
        """Store the project profile (metadata fields + mark buttons) for every client."""
        from flir_research_interface.analysis.profile import save_profile

        try:
            body = await request.json()
            return await run_in_threadpool(save_profile, app.state.experiments_root, body)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/visible/live.mjpeg")
    def visible_live() -> Response:
        """Low-rate MJPEG of the visible camera; one ffmpeg per viewer, killed on disconnect."""
        from starlette.background import BackgroundTask
        from starlette.responses import StreamingResponse

        from flir_research_interface.visible.preview import MAX_VIEWERS

        if preview_factory is None:
            raise HTTPException(
                503, "visible preview unavailable: ffmpeg or RTSP credentials not configured"
            )
        viewers: set[Any] = app.state.__dict__.setdefault("preview_viewers", set())
        for stale in [v for v in viewers if getattr(v, "_closed", False)]:
            viewers.discard(stale)
        if len(viewers) >= MAX_VIEWERS:
            raise HTTPException(409, f"visible preview already open in {MAX_VIEWERS} viewers")
        relay = preview_factory()
        viewers.add(relay)

        def _done() -> None:
            relay.close()
            viewers.discard(relay)

        return StreamingResponse(
            relay.aiter(),
            media_type=relay.content_type,
            headers={"Cache-Control": "no-store"},
            background=BackgroundTask(_done),
        )

    # -- recording -------------------------------------------------------------------------

    def _recording_extra(req: RecordingStartRequest) -> dict[str, Any]:
        from flir_research_interface.analysis.calibration import load_alignment
        from flir_research_interface.analysis.profile import load_profile

        extra: dict[str, Any] = {}
        prof = load_profile(app.state.experiments_root)
        extra["profile"] = {"name": prof["name"], "marks": [m["label"] for m in prof["marks"]]}
        alignment = load_alignment(app.state.experiments_root)
        if alignment:
            extra["visible_alignment"] = alignment
        if req.rois is not None:
            extra["rois"] = _rois_with_labels(req.rois)
        return extra

    def _rois_with_labels(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Validate ROI geometry/optics (parse_rois) and re-attach the operator's names/colours."""
        from flir_research_interface.analysis.series import parse_rois

        try:
            parsed = parse_rois(json.dumps(raw))
        except ValueError as exc:
            raise HTTPException(400, f"rois: {exc}") from exc
        by_id = {r["id"]: r for r in raw}
        for r in parsed:
            src = by_id.get(r["id"], {})
            if isinstance(src.get("name"), str) and src["name"].strip():
                r["name"] = src["name"].strip()[:40]
            if isinstance(src.get("color"), str):
                r["color"] = src["color"]
        return parsed

    app.state.nuc_restore = None
    nuc_settle_s = 2.5  # the A70 freezes its image for ~2 s while it performs a NUC

    def _nuc_hold_begin(svc: AcquisitionService, *, nuc_first: bool) -> dict[str, Any] | None:
        """NUC now (optional), then NUCMode=Off; metadata block, or None if unsupported."""
        try:
            before = svc.backend.camera_info().get("nuc_mode")
        except Exception:  # noqa: BLE001 - a backend without the node just skips the hold
            return None
        if before is None:
            return None
        did_nuc = False
        if nuc_first and before != "Off":
            try:
                svc.backend.execute("NUCAction")
                did_nuc = True
                if getattr(svc.backend, "name", "") == "spinnaker":
                    time.sleep(nuc_settle_s)
            except Exception:  # noqa: BLE001
                logger.exception("pre-record NUC failed; continuing")
        try:
            svc.backend.set_parameters({"NUCMode": "Off"})
        except Exception:  # noqa: BLE001
            logger.exception("could not set NUCMode=Off; recording without the hold")
            return None
        app.state.nuc_restore = before
        return {"mode_before": before, "nuc_before_start": did_nuc}

    def _nuc_hold_end() -> None:
        before = app.state.nuc_restore
        app.state.nuc_restore = None
        svc = service()
        if before is None or svc is None:
            return
        try:
            svc.backend.set_parameters({"NUCMode": before})
        except Exception:  # noqa: BLE001
            logger.exception("could not restore NUCMode=%s", before)

    async def _start_recording(
        req: RecordingStartRequest, *, attach_service: bool = True, nuc_first: bool = True
    ) -> tuple[Recorder, Path, dict[str, Any]]:
        svc = service()
        if svc is None or svc.state != ServiceState.ACQUIRING:
            raise HTTPException(409, "camera is not acquiring")
        if recorder() is not None and recorder().state == RecorderState.RECORDING:  # type: ignore[union-attr]
            raise HTTPException(409, "already recording")
        extra = _recording_extra(req)
        hold = None
        if req.nuc_hold and app.state.nuc_restore is None:
            hold = await run_in_threadpool(_nuc_hold_begin, svc, nuc_first=nuc_first)
        elif req.nuc_hold and app.state.nuc_restore is not None:  # armed: held since arm time
            hold = {"mode_before": app.state.nuc_restore, "nuc_before_start": False}
        if hold is not None:
            extra["nuc_hold"] = hold
        rec = Recorder(
            svc if attach_service else None,
            experiments_root=app.state.experiments_root,
            min_free_gb=app.state.min_free_gb,
            every_nth=req.every_nth,
        )
        kwargs: dict[str, Any] = {
            "name": req.name,
            "metadata": req.metadata,
            "extra": extra or None,
        }
        if not attach_service:
            kwargs["camera_info"] = await run_in_threadpool(svc.backend.camera_info)
        try:
            exp_dir = await run_in_threadpool(rec.start, **kwargs)
        except RuntimeError as exc:
            raise HTTPException(507 if "free space" in str(exc) else 400, str(exc)) from exc
        app.state.recorder = rec
        if hold is not None and hold.get("nuc_before_start"):
            rec.note_event("nuc", {"reason": "pre-record", "requested_by": "nuc_hold"})
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
        return rec, exp_dir, visible

    @app.post("/api/recording/start")
    async def recording_start(req: RecordingStartRequest) -> dict[str, Any]:
        if app.state.armer is not None:
            raise HTTPException(409, "a recording is armed; disarm it or let the trigger start it")
        rec, exp_dir, visible = await _start_recording(req)
        return {"state": rec.state.value, "experiment_dir": str(exp_dir), "visible": visible}

    # -- M11: armed recording ------------------------------------------------------------------

    app.state.armer = None
    app.state.arm_task = None
    app.state.arm_req = None

    async def _arm_loop() -> None:
        from flir_research_interface.recording.arm import Armer

        try:
            while True:
                await asyncio.sleep(0.05)
                armer: Armer | None = app.state.armer
                if armer is None:
                    return
                action = armer.take_pending()
                if action == "start":
                    req: ArmRequest = app.state.arm_req
                    try:
                        rec, _exp_dir, _vis = await _start_recording(
                            req, attach_service=False, nuc_first=False
                        )
                    except HTTPException as exc:
                        logger.error("armed start failed: %s", exc.detail)
                        _disarm()
                        _nuc_hold_end()
                        return
                    pre = armer.attach(rec)
                    rec.note_event(
                        "trigger",
                        {
                            "start": armer.spec.start.__dict__,
                            "end": armer.spec.end.__dict__,
                            "pretrigger_frames": pre,
                            "watched_value": armer.last_value,
                            "frame_id": armer.started_frame_id,
                        },
                    )
                elif action == "stop":
                    live = armer.detach()
                    if live is not None:
                        live.note_event(
                            "trigger_end",
                            {
                                "reason": armer.machine.reason,
                                "watched_value": armer.last_value,
                                "frame_id": armer.ended_frame_id,
                            },
                        )
                        await _finalize_recording()
                    _disarm()
                    return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("arm loop failed")
            _disarm()

    def _disarm() -> None:
        armer = app.state.armer
        svc = service()
        if armer is not None and svc is not None:
            svc.remove_listener(armer.on_frame)
        app.state.armer = None
        app.state.arm_req = None

    @app.post("/api/recording/arm")
    async def recording_arm(req: ArmRequest) -> dict[str, Any]:
        from flir_research_interface.analysis.series import parse_rois
        from flir_research_interface.recording.arm import Armer
        from flir_research_interface.recording.trigger import parse_trigger

        svc = service()
        if svc is None or svc.state != ServiceState.ACQUIRING:
            raise HTTPException(409, "camera is not acquiring")
        if app.state.armer is not None:
            raise HTTPException(409, "already armed")
        if recorder() is not None and recorder().state == RecorderState.RECORDING:  # type: ignore[union-attr]
            raise HTTPException(409, "already recording")
        try:
            spec = parse_trigger(req.trigger)
            rois = parse_rois(json.dumps(req.rois)) if req.rois else []
        except ValueError as exc:
            raise HTTPException(400, f"trigger: {exc}") from exc
        _recording_extra(req)  # validate the rest now, not when the trigger fires
        # Ring sizing: the measured rate is unreliable right after connect, so never assume
        # fewer than 60 fps (A70 max is 30; 2 s at 60 fps of 640x480 uint16 is ~74 MB).
        fps = float(svc.stats().get("camera_fps") or 0)
        armer = Armer(spec, rois, fps_hint=max(fps, 60.0))
        if req.nuc_hold:
            await run_in_threadpool(_nuc_hold_begin, svc, nuc_first=True)
        app.state.armer = armer
        app.state.arm_req = req
        svc.add_listener(armer.on_frame)
        app.state.arm_task = asyncio.create_task(_arm_loop())
        return {"state": "armed", "armed": armer.status()}

    @app.post("/api/recording/disarm")
    async def recording_disarm() -> dict[str, Any]:
        armer = app.state.armer
        if armer is None:
            raise HTTPException(409, "not armed")
        rec = armer.detach()
        _disarm()
        task = app.state.arm_task
        if task is not None:
            task.cancel()
            app.state.arm_task = None
        if rec is not None:  # disarmed mid-recording: finish the recording cleanly
            rec.note_event("trigger_end", {"reason": "disarmed"})
            manifest = await _finalize_recording()
            return {"state": "idle", "manifest": manifest}
        _nuc_hold_end()
        return {"state": "idle"}

    @app.post("/api/recording/arm/start")
    async def recording_arm_start() -> dict[str, Any]:
        """Manual start of an armed recording (start kind 'manual', or to override a trigger)."""
        armer = app.state.armer
        if armer is None or not armer.manual_start():
            raise HTTPException(409, "not armed, or already started")
        return {"state": "starting"}

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
        armer = app.state.armer
        if rec is None and armer is not None:
            probe = root if root.exists() else root.parent
            free = shutil.disk_usage(probe).free / 1e9 if probe.exists() else None
            return {
                "state": "armed",
                "armed": armer.status(),
                "experiments_root": str(root),
                "free_space_gb": free,
                "min_free_gb": app.state.min_free_gb,
                "visible": _visible_status(),
            }
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

    def _dir_size(path: Path) -> int:
        total = 0
        for root_dir, _dirs, files in os.walk(path):
            for f in files:
                try:
                    total += (Path(root_dir) / f).stat().st_size
                except OSError:
                    pass
        return total

    def _roots() -> list[tuple[str, Path]]:
        """(library, root) pairs to resolve runs in: always local, plus the drive when mounted."""
        roots: list[tuple[str, Path]] = [("local", Path(app.state.experiments_root))]
        drive = storage.load_storage_config(app.state.experiments_root)["drive"]
        if drive and Path(drive["root"]).is_dir():  # only when the registered drive is connected
            roots.append(("drive", Path(drive["root"])))
        return roots

    @app.get("/api/experiments")
    def experiments() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for lib, root in _roots():
            for it in list_experiments(root, library=lib):
                it["size_bytes"] = _dir_size(root / str(it.get("name", "")))
                items.append(it)
        # newest first across both libraries (names are timestamped)
        items.sort(key=lambda e: str(e.get("name", "")), reverse=True)
        return items

    @app.get("/api/experiments/summary")
    def experiments_summary() -> dict[str, Any]:
        """Runs on disk and how much of the disk they use (for the experiments page header)."""
        root: Path = app.state.experiments_root
        dirs = [p for p in root.iterdir() if p.is_dir()] if root.is_dir() else []
        probe = root if root.exists() else root.parent
        free = shutil.disk_usage(probe).free / 1e9 if probe.exists() else 0.0
        return {
            "count": len(dirs),
            "size_bytes": sum(_dir_size(d) for d in dirs),
            "free_space_gb": float(free),
            "experiments_root": str(root),
        }

    def _exp_dir(name: str) -> Path:
        if "/" in name or "\\" in name or name in ("", ".", ".."):
            raise HTTPException(400, "invalid experiment name")
        for _lib, root in _roots():
            d = root / name
            if not d.is_dir():
                continue
            if not contained(root, d):  # a symlink escaping the root
                raise HTTPException(400, "experiment path is outside the experiments root")
            return d
        raise HTTPException(404, f"experiment {name!r} not found")

    # -- external-drive storage (offload) ------------------------------------------------------

    @app.get("/api/storage/volumes")
    def storage_volumes() -> list[dict[str, Any]]:
        """External drives that can be registered as the offload target (filtered, writable)."""
        drives = storage.selectable_drives(sys.platform)
        cfg = storage.load_storage_config(app.state.experiments_root)["drive"]
        registered = cfg["mount"] if cfg else None
        for d in drives:
            d["is_registered"] = d["mount"] == registered
        return drives

    def _storage_state() -> dict[str, Any]:
        root: Path = app.state.experiments_root
        probe = root if root.exists() else root.parent
        local = {
            "root": str(root),
            "free_bytes": int(shutil.disk_usage(probe).free) if probe.exists() else 0,
            "total_bytes": int(shutil.disk_usage(probe).total) if probe.exists() else 0,
        }
        drive = storage.load_storage_config(root)["drive"]
        connected = bool(drive and Path(drive["root"]).is_dir())
        drive_info = None
        if drive:
            drive_info = {**drive, "connected": connected}
            if connected:
                du = shutil.disk_usage(drive["mount"])
                drive_info["free_bytes"], drive_info["total_bytes"] = int(du.free), int(du.total)
        return {"local": local, "drive": drive_info}

    @app.get("/api/storage")
    def storage_state() -> dict[str, Any]:
        return _storage_state()

    @app.put("/api/storage/drive")
    def storage_register(req: RegisterDriveRequest) -> dict[str, Any]:
        try:
            storage.register_drive(app.state.experiments_root, req.mount)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return _storage_state()

    @app.delete("/api/storage/drive")
    def storage_forget() -> dict[str, Any]:
        storage.forget_drive(app.state.experiments_root)
        return _storage_state()

    @app.post("/api/experiments/{name}/move")
    async def move_experiment_route(name: str, req: MoveRequest) -> dict[str, Any]:
        """Offload a run to the drive (``to:"drive"``) or bring it back (``to:"local"``).

        Copy → verify → delete-source, in the background; poll ``…/move/status``. Guarded by the
        per-run render lock so a move never races a render/regenerate of the same run.
        """
        if req.to not in ("drive", "local"):
            raise HTTPException(400, "to must be 'drive' or 'local'")
        rec = recorder()
        src = _exp_dir(name)  # 404 if unknown
        if (
            rec is not None
            and rec.experiment_dir is not None
            and rec.experiment_dir.resolve() == src.resolve()
        ):
            raise HTTPException(409, "this run is being recorded right now")
        existing = app.state.move_jobs.get(name)
        if existing is not None and existing["state"] == "running":
            return existing
        cfg = storage.load_storage_config(app.state.experiments_root)["drive"]
        if not cfg or not Path(cfg["root"]).is_dir():
            raise HTTPException(409, "no external drive is connected; register one first")
        dst_root = Path(cfg["root"]) if req.to == "drive" else Path(app.state.experiments_root)
        if contained(dst_root, src):
            raise HTTPException(409, f"{name} is already on the {req.to} storage")

        job: dict[str, Any] = {
            "state": "running", "to": req.to, "done": 0, "total": 0, "error": None,
        }
        app.state.move_jobs[name] = job

        def _work() -> None:
            def _cb(done: int, total: int) -> None:
                job["done"], job["total"] = done, total

            storage.move_experiment(src, dst_root, on_progress=_cb)

        async def _job() -> None:
            try:
                async with app.state.render_locks.get(name):
                    await run_in_threadpool(_work)
                job["state"] = "done"
            except ValueError as exc:  # not enough space
                job["state"], job["error"] = "error", str(exc)
            except Exception as exc:  # noqa: BLE001 - surface to the poller; source is left intact
                job["state"], job["error"] = "error", str(exc)
                logger.exception("move failed for %s", name)

        task = asyncio.create_task(_job())
        app.state.render_tasks.add(task)
        task.add_done_callback(app.state.render_tasks.discard)
        return job

    @app.get("/api/experiments/{name}/move/status")
    def move_status(name: str) -> dict[str, Any]:
        return app.state.move_jobs.get(name) or {"state": "idle"}

    def _open(name: str) -> ExperimentReader:
        d = _exp_dir(name)
        try:
            return ExperimentReader(d)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            raise HTTPException(404, f"experiment {name!r} is not readable: {exc}") from exc

    def _reveal(path: Path) -> dict[str, Any]:
        if not any(contained(root, path) for _lib, root in _roots()):
            raise HTTPException(400, "path is outside the experiments roots")
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
        info["size_bytes"] = _dir_size(r.path)
        exp_dir = r.path / "exports"
        info["exports"] = (
            sorted(
                (
                    {"name": p.name, "bytes": p.stat().st_size}
                    for p in exp_dir.iterdir()
                    if p.is_file()
                    and not p.name.startswith(".")
                    and not p.name.endswith(".part.mp4")
                ),
                key=lambda e: str(e["name"]),
            )
            if exp_dir.is_dir()
            else []
        )
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

    @app.put("/api/experiments/{name}/rois")
    def experiment_rois_put(name: str, req: RoisRequest) -> dict[str, Any]:
        """Persist the ROIs from playback into the recording so derived exports can match them.

        The store's counts are never touched — only ``metadata.json['rois']``. Geometry and
        per-ROI optics (emissivity / reflected / distance) are validated by ``parse_rois``.
        """
        from flir_research_interface.recording.metadata import set_experiment_rois

        d = _exp_dir(name)
        rois = _rois_with_labels(req.rois)
        try:
            set_experiment_rois(d, rois)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"rois": len(rois)}

    @app.post("/api/experiments/{name}/export/derived")
    async def export_derived_route(name: str, video: bool = True) -> dict[str, Any]:
        """Start (or return) a background regenerate of the ROI-dependent derived files.

        roi_series.csv, README/roi_plot/peak-frame images and (unless ``video=false``) the
        ROI-annotated thermal video — from the recording's stored ROIs. ``video=false`` is the
        quick option: plot + CSV + images only, skipping the slow video encode. The clean thermal
        video never depends on the ROIs and is not re-rendered here. Returns a job record
        immediately; poll ``/export/derived/status``. Pair with ``PUT /rois`` after editing.
        """
        from flir_research_interface.analysis.thermal_video import render_thermal_video

        _exp_dir(name)  # 404 early if the run is gone
        existing = app.state.derived_jobs.get(name)
        if existing is not None and existing["state"] == "running":
            return existing
        job: dict[str, Any] = {"state": "running", "step": "starting", "done": 0, "total": 0,
                               "exports": None, "error": None}
        app.state.derived_jobs[name] = job

        def _work() -> None:
            exp_dir = _exp_dir(name)
            job["step"] = "roi series"
            _export_roi_series(exp_dir)
            job["step"] = "images"
            _write_run_summary(exp_dir)
            reader = ExperimentReader(exp_dir)
            if video and reader.metadata.get("rois"):
                job["step"] = "roi video"

                def _cb(done: int, total: int) -> None:
                    job["done"], job["total"] = done, total

                render_thermal_video(reader, with_rois=True, on_progress=_cb)

        async def _job() -> None:
            try:
                lock = app.state.render_locks.get(name)
                if lock.locked():  # a post-stop render (or another regenerate) is finishing first
                    job["step"] = "waiting for the current render"
                async with lock:
                    await run_in_threadpool(_work)
                job["step"] = "done"
                job["exports"] = experiment_info(name)["exports"]
                job["state"] = "done"
            except Exception as exc:  # noqa: BLE001 - surface the failure to the poller
                job["state"], job["error"] = "error", str(exc)
                logger.exception("derived regenerate failed for %s", name)

        task = asyncio.create_task(_job())
        app.state.render_tasks.add(task)
        task.add_done_callback(app.state.render_tasks.discard)
        return job

    @app.get("/api/experiments/{name}/export/derived/status")
    def export_derived_status(name: str) -> dict[str, Any]:
        """Progress of the current/last derived regenerate for this run (see the POST)."""
        return app.state.derived_jobs.get(name) or {"state": "idle"}

    @app.post("/api/experiments/{name}/export/media")
    async def export_media_route(name: str, req: MediaRequest) -> dict[str, Any]:
        """Start a background media-export render (MP4/GIF of a window with overlays).

        Returns a job record immediately; poll ``/export/media/status``. When ``rois`` is given the
        on-screen ROIs are persisted first (like the derived flow); else the stored ROIs are used.
        """
        from flir_research_interface.analysis.media import MediaOptions, render_clip
        from flir_research_interface.recording.metadata import set_experiment_rois

        _exp_dir(name)
        if req.rois is not None:
            set_experiment_rois(_exp_dir(name), _rois_with_labels(req.rois))
        existing = app.state.media_jobs.get(name)
        if existing is not None and existing["state"] == "running":
            return existing
        job: dict[str, Any] = {"state": "running", "step": "starting", "done": 0, "total": 0,
                               "file": None, "error": None}
        app.state.media_jobs[name] = job
        opts = MediaOptions(
            start=req.start, stop=req.stop, step=req.step, scale=req.scale, speed=req.speed,
            fps=req.fps, fmt=req.fmt, with_rois=req.with_rois, frame_stats=req.frame_stats,
            timestamp=req.timestamp, colorbar=req.colorbar, title=req.title,
            plot_roi=req.plot_roi, plot_rois=tuple(req.plot_rois), plot_stat=req.plot_stat,
            plot_stats=tuple(req.plot_stats), plot_series=_parse_series(req.plot_series),
            overlay_rois=tuple(req.overlay_rois), visible_opacity=req.visible_opacity,
            palette=req.palette,
        )

        def _work() -> dict[str, Any]:
            def _cb(done: int, total: int) -> None:
                job["step"], job["done"], job["total"] = "encoding", done, total
            return render_clip(_open(name), opts, on_progress=_cb)

        async def _job() -> None:
            try:
                async with app.state.render_locks.get(name):
                    info = await run_in_threadpool(_work)
                job["file"] = {
                    "name": info["name"], "bytes": info["bytes"], "note": info.get("note"),
                }
                job["step"], job["state"] = "done", "done"
            except (ValueError, RuntimeError) as exc:
                job["state"], job["error"] = "error", str(exc)
            except Exception as exc:  # noqa: BLE001
                job["state"], job["error"] = "error", str(exc)
                logger.exception("media export failed for %s", name)

        task = asyncio.create_task(_job())
        app.state.render_tasks.add(task)
        task.add_done_callback(app.state.render_tasks.discard)
        return job

    @app.get("/api/experiments/{name}/export/media/status")
    def export_media_status(name: str) -> dict[str, Any]:
        return app.state.media_jobs.get(name) or {"state": "idle"}

    @app.get("/api/experiments/{name}/export/media/preview")
    async def export_media_preview(
        name: str, index: int, scale: int = Query(default=1, ge=1, le=4),
        with_rois: bool = True, frame_stats: bool = False, timestamp: bool = True,
        colorbar: bool = True, title: str | None = None,
        plot_roi: int | None = None,
        plot_rois: Annotated[list[int] | None, Query()] = None,
        plot_stats: Annotated[list[str] | None, Query()] = None,
        plot_series: Annotated[list[str] | None, Query()] = None,
        overlay_rois: Annotated[list[int] | None, Query()] = None,
        plot_stat: str = "mean", start: int = 0, stop: int = 0, visible_opacity: float = 0.0,
        palette: str = "inferno",
    ) -> Response:
        """One composed frame (same overlays as the export) as PNG for the editor preview."""
        from flir_research_interface.analysis.media import MediaOptions, compose_preview

        opts = MediaOptions(scale=scale, with_rois=with_rois, frame_stats=frame_stats,
                            timestamp=timestamp, colorbar=colorbar, title=title,
                            plot_roi=plot_roi, plot_rois=tuple(plot_rois or ()),
                            plot_stat=plot_stat, plot_stats=tuple(plot_stats or ()),
                            plot_series=_parse_series(plot_series or []),
                            overlay_rois=tuple(overlay_rois or ()),
                            visible_opacity=max(0.0, min(1.0, visible_opacity)), palette=palette,
                            start=start, stop=stop)
        try:
            png = await run_in_threadpool(compose_preview, _open(name), opts, index)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return Response(content=png, media_type="image/png")

    @app.get("/api/experiments/{name}/series")
    async def experiment_series(
        name: str, rois: str, valid: str | None = None, max_points: int = 0
    ) -> dict[str, Any]:
        """ROI values on every frame of a recording (spots: value; areas: min/max/mean/std/n).
        ``valid=lo,hi`` (°C) applies segmentation: pixels outside the range are ignored."""
        from flir_research_interface.analysis.series import parse_rois, roi_series

        try:
            parsed = parse_rois(rois)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        valid_c: tuple[float, float] | None = None
        if valid:
            try:
                lo_s, hi_s = valid.split(",", 1)
                valid_c = (float(lo_s), float(hi_s))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="valid must be 'lo,hi'") from exc
        r = _open(name)
        stride = 1
        if max_points and r.n_frames > max_points:
            stride = -(-r.n_frames // max_points)  # ceil; keeps ~max_points plot points
        out = await run_in_threadpool(lambda: roi_series(r, parsed, valid_c=valid_c, stride=stride))
        out["events"] = r.events
        return out

    @app.get("/api/experiments/{name}/frames")
    def experiment_frame_block(
        name: str, start: int = 0, count: int = Query(32, ge=1, le=256)
    ) -> Response:
        """A run of frames in one response: repeated [uint32 length][frame message]. One request
        instead of one per frame keeps playback smooth (block Zarr reads are ~30x cheaper)."""
        r = _open(name)
        if not 0 <= start < r.n_frames:
            raise HTTPException(404, f"frame start {start} out of range [0, {r.n_frames})")
        stop = min(start + count, r.n_frames)
        block = r.counts_block(start, stop)  # one decompression per chunk, not per frame
        parts: list[bytes] = []
        for k in range(stop - start):
            i = start + k
            frame = Frame(
                frame_id=int(r._frame_id[i]),
                device_timestamp_ns=int(r._dev_ts[i]),
                host_timestamp_ns=int(r._host_ts[i]),
                pixel_format=r.pixel_format,
                ir_format=str(r.ir_format or ""),
                counts=block[k],
                incomplete=False,
            )
            msg = encode_frame_message(
                frame,
                extra={"index": i, "n_frames": r.n_frames, "t_s": r.t_s(i), "source": "playback"},
            )
            parts.append(struct.pack(">I", len(msg)) + msg)
        return Response(
            content=b"".join(parts),
            media_type="application/octet-stream",
            headers={"x-frame-start": str(start), "x-frame-count": str(stop - start)},
        )

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

    @app.delete("/api/experiments/{name}")
    async def delete_experiment(name: str) -> dict[str, str]:
        """Remove a run folder for good (no trash: the acquisition Mac is short of disk)."""
        d = _exp_dir(name)
        rec = recorder()
        if (
            rec is not None
            and rec.experiment_dir is not None
            and rec.experiment_dir.resolve() == d.resolve()
        ):
            raise HTTPException(409, "this run is being recorded right now; stop it first")
        await run_in_threadpool(shutil.rmtree, d)
        logger.warning("deleted experiment %s", d)
        return {"deleted": name}

    @app.post("/api/experiments/{name}/export/report")
    async def export_report_route(name: str) -> dict[str, Any]:
        from flir_research_interface.analysis.report import write_report

        return await run_in_threadpool(write_report, _open(name))

    @app.get("/api/experiments/{name}/report.pdf")
    def experiment_report(name: str) -> Response:
        from starlette.responses import FileResponse

        path = _exp_dir(name) / "exports" / "report.pdf"
        if not path.is_file():
            raise HTTPException(404, "report not generated yet")
        return FileResponse(path, media_type="application/pdf")

    @app.post("/api/experiments/{name}/export/frames")
    async def export_frames_route(name: str, req: FrameRangeRequest) -> dict[str, Any]:
        from flir_research_interface.analysis.export import export_frame_range

        r = _open(name)
        try:
            return await run_in_threadpool(
                export_frame_range, r, req.start, req.stop, req.step, req.format
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/experiments/{name}/export/thermal-video")
    async def export_thermal_video_route(name: str, rois: bool = False) -> dict[str, Any]:
        """Re-render the viewing video; ``?rois=true`` renders the ROI-annotated version."""
        from flir_research_interface.analysis.thermal_video import render_thermal_video

        try:
            reader = _open(name)
            return await run_in_threadpool(lambda: render_thermal_video(reader, with_rois=rois))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/experiments/{name}/exports/{file}")
    def experiment_export_file(name: str, file: str) -> Response:
        """Any derived file from the run's exports/ folder (PNG, MP4, CSV, PDF, zip, TIFF…)."""
        from starlette.responses import FileResponse

        if "/" in file or "\\" in file or file.startswith("."):
            raise HTTPException(400, "invalid file name")
        path = _exp_dir(name) / "exports" / file
        if not path.is_file():
            raise HTTPException(404, f"exports/{file} not found")
        return FileResponse(path, headers={"Accept-Ranges": "bytes"})

    @app.get("/api/experiments/{name}/exports/clips/{file}")
    def experiment_clip_file(name: str, file: str) -> Response:
        """A media-export clip from the run's exports/clips/ folder (MP4 / GIF)."""
        from starlette.responses import FileResponse

        if "/" in file or "\\" in file or file.startswith("."):
            raise HTTPException(400, "invalid file name")
        path = _exp_dir(name) / "exports" / "clips" / file
        if not path.is_file():
            raise HTTPException(404, f"clips/{file} not found")
        return FileResponse(path, headers={"Accept-Ranges": "bytes"})

    @app.get("/api/experiments/{name}/thermal_preview.mp4")
    def experiment_thermal_video(name: str) -> Response:
        from starlette.responses import FileResponse

        path = _exp_dir(name) / "exports" / "thermal_preview.mp4"
        if not path.is_file():
            raise HTTPException(404, "thermal preview video not rendered yet")
        return FileResponse(path, media_type="video/mp4", headers={"Accept-Ranges": "bytes"})

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

    @app.get("/api/experiments/{name}/visible.mp4")
    def experiment_visible_video(name: str) -> Response:
        from starlette.responses import FileResponse

        path = _exp_dir(name) / "visible.mp4"
        if not path.is_file():
            raise HTTPException(404, "this recording has no visible video")
        return FileResponse(path, media_type="video/mp4", headers={"Accept-Ranges": "bytes"})

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
