"""Spinnaker/PySpin backend for FLIR A50/A70-class cameras.

Every node name used here was observed on the FLIR A70 (fw 42.0.0) node map dumped by
``fri-probe`` on 2026-09-01 (see docs/radiometry.md). PySpin is imported lazily so the rest of
the package works without the SDK.

Buffer ownership follows FLIR's examples: ``GetNextImage`` -> ``IsIncomplete`` -> copy
``GetNDArray`` -> ``Release``; teardown ``EndAcquisition`` -> ``DeInit`` -> ``del cam`` ->
``cam_list.Clear()`` -> ``system.ReleaseInstance()``.
"""

from __future__ import annotations

import logging
import time
import traceback
from collections.abc import Iterator
from typing import Any

import numpy as np

from flir_research_interface.camera.base import (
    CameraBackend,
    CameraError,
    DeviceDescriptor,
    Frame,
    NotConnectedError,
)
from flir_research_interface.camera.controls import COMMANDS, ENUM_NODES, validate_values
from flir_research_interface.radiometry.temperature_linear import KELVIN_OFFSET, IRFormat

logger = logging.getLogger(__name__)

OBJECT_PARAMETER_NODES: tuple[str, ...] = (
    "ObjectEmissivity",
    "ReflectedTemperature",
    "AtmosphericTemperature",
    "ObjectDistance",
    "RelativeHumidity",
    "ExtOpticsTemperature",
    "ExtOpticsTransmission",
    "EstimatedTransmission",
    "UseWindowTemperature",
)
"""Category ``ObjectParameters`` on the A70. Temperatures are Kelvin, humidity/transmission 0-1."""

CALIBRATION_CONSTANT_NODES: tuple[str, ...] = (
    "R",
    "B",
    "F",
    "J0",
    "J1",
    "X",
    "alpha1",
    "alpha2",
    "beta1",
    "beta2",
)
"""Category ``Measurement``: FLIR signal-to-temperature constants (recorded as metadata only)."""

IDENTITY_NODES: tuple[str, ...] = (
    "DeviceVendorName",
    "DeviceModelName",
    "DeviceSerialNumber",
    "DeviceVersion",
    "DeviceUserID",
    "DeviceManufacturerInfo",
    "LensName",
    "Segment",
    "PowerMode",
    "LensConnected",
    "FlipValue",
)
ACQUISITION_NODES: tuple[str, ...] = (
    "Width",
    "Height",
    "OffsetX",
    "OffsetY",
    "SensorWidth",
    "SensorHeight",
    "PixelFormat",
    "IRFormat",
    "IRFrameRate",
    "AcquisitionFrameRate",
    "AcquisitionMode",
    "ImageMode",
    "VideoSourceSelector",
    "ImageCompressionMode",
    "NUCMode",
    "NoiseReduction",
    "ImageAdjustMode",
    "CurrentCase",
    "NumCases",
    "GevTimestampTickFrequency",
    "PtpEnable",
    "PtpStatus",
    "GevSCPSPacketSize",
    "DeviceTemperature",
    "DeviceTemperatureSelector",
)

STREAM_COUNTER_NODES: dict[str, str] = {
    "delivered": "StreamDeliveredFrameCount",
    "received": "StreamReceivedFrameCount",
    "lost": "StreamLostFrameCount",
    "dropped": "StreamDroppedFrameCount",
    "incomplete": "StreamIncompleteFrameCount",
    "missed_packets": "StreamMissedPacketCount",
    "resend_requests": "StreamPacketResendRequestCount",
}


def build_camera_info(
    raw: dict[str, Any],
    *,
    cases: list[dict[str, Any]],
    spinnaker_version: str,
    ir_format_before: str | None,
    timestamp_offset_ns: int | None = None,
) -> dict[str, Any]:
    """Assemble the auditable camera_info dict from raw node values (pure function)."""
    cases_c = [
        {
            **c,
            "low_c": (c["low_k"] - KELVIN_OFFSET) if c.get("low_k") is not None else None,
            "high_c": (c["high_k"] - KELVIN_OFFSET) if c.get("high_k") is not None else None,
        }
        for c in cases
    ]
    current = raw.get("CurrentCase")
    active = next((c for c in cases_c if c.get("index") == current), None)
    return {
        "backend": "spinnaker",
        "spinnaker_version": spinnaker_version,
        "vendor": raw.get("DeviceVendorName"),
        "model": raw.get("DeviceModelName"),
        "serial": raw.get("DeviceSerialNumber"),
        "firmware": raw.get("DeviceVersion"),
        "lens": raw.get("LensName"),
        "width": raw.get("Width"),
        "height": raw.get("Height"),
        "pixel_format": raw.get("PixelFormat"),
        "ir_format": raw.get("IRFormat"),
        "ir_format_before_connect": ir_format_before,
        "frame_rate_hz": raw.get("AcquisitionFrameRate"),
        "ir_frame_rate": raw.get("IRFrameRate"),
        "active_case": active,
        "measurement_cases": cases_c,
        "object_parameters": {k: raw.get(k) for k in OBJECT_PARAMETER_NODES},
        "calibration_constants": {k: raw.get(k) for k in CALIBRATION_CONSTANT_NODES},
        "nuc_mode": raw.get("NUCMode"),
        "timestamp_tick_hz": raw.get("GevTimestampTickFrequency"),
        "camera_minus_host_ns": timestamp_offset_ns,
        "nodes": {k: raw.get(k) for k in IDENTITY_NODES + ACQUISITION_NODES},
    }


def _pyspin() -> Any:
    try:
        import PySpin  # noqa: N813

        return PySpin
    except ImportError as exc:  # pragma: no cover - depends on machine
        raise CameraError(
            "PySpin is not importable; install the Spinnaker SDK and matching wheel "
            "(run `fri-sdk-check`)."
        ) from exc


def _read(ps: Any, nodemap: Any, name: str) -> Any:
    """Read any readable node as a Python value; None if absent/unreadable."""
    try:
        node = nodemap.GetNode(name)
        if node is None or not ps.IsReadable(node):
            return None
        t = node.GetPrincipalInterfaceType()
        if t == ps.intfIInteger:
            return int(ps.CIntegerPtr(node).GetValue())
        if t == ps.intfIFloat:
            return float(ps.CFloatPtr(node).GetValue())
        if t == ps.intfIBoolean:
            return bool(ps.CBooleanPtr(node).GetValue())
        if t == ps.intfIString:
            return str(ps.CStringPtr(node).GetValue())
        if t == ps.intfIEnumeration:
            return str(ps.CEnumEntryPtr(ps.CEnumerationPtr(node).GetCurrentEntry()).GetSymbolic())
        return str(ps.CValuePtr(node).ToString())
    except Exception:  # noqa: BLE001 - vendor nodes may throw on read
        return None


def _set_enum(ps: Any, nodemap: Any, name: str, symbolic: str) -> str:
    """Set enumeration ``name`` to ``symbolic``; return previous symbolic value."""
    node = ps.CEnumerationPtr(nodemap.GetNode(name))
    if not ps.IsWritable(node):
        raise CameraError(f"node {name!r} is not writable")
    previous = str(ps.CEnumEntryPtr(node.GetCurrentEntry()).GetSymbolic())
    entry = ps.CEnumEntryPtr(node.GetEntryByName(symbolic))
    if not ps.IsReadable(entry):
        raise CameraError(f"entry {symbolic!r} not available on node {name!r}")
    node.SetIntValue(entry.GetValue())
    return previous


def _enum_entries(ps: Any, nodemap: Any, name: str) -> list[str]:
    """Symbolic names of the currently available entries of enumeration ``name``."""
    try:
        node = ps.CEnumerationPtr(nodemap.GetNode(name))
        if not ps.IsReadable(node):
            return []
        out: list[str] = []
        for entry in node.GetEntries():
            e = ps.CEnumEntryPtr(entry)
            if ps.IsReadable(e):
                out.append(str(e.GetSymbolic()))
        return out
    except Exception:  # noqa: BLE001 - vendor nodes may throw
        return []


def _write(ps: Any, nodemap: Any, name: str, value: Any) -> None:
    """Write one node by its GenICam interface type; ``CameraError`` if not writable."""
    node = nodemap.GetNode(name)
    if node is None or not ps.IsWritable(node):
        raise CameraError(f"node {name!r} is not writable")
    t = node.GetPrincipalInterfaceType()
    if t == ps.intfIEnumeration:
        _set_enum(ps, nodemap, name, str(value))
    elif t == ps.intfIFloat:
        f = ps.CFloatPtr(node)
        lo, hi = float(f.GetMin()), float(f.GetMax())
        if not lo <= float(value) <= hi:
            raise ValueError(f"{name} must be within {lo}…{hi} on this camera")
        f.SetValue(float(value))
    elif t == ps.intfIInteger:
        i = ps.CIntegerPtr(node)
        lo, hi = int(i.GetMin()), int(i.GetMax())
        if not lo <= int(value) <= hi:
            raise ValueError(f"{name} must be within {lo}…{hi} on this camera")
        i.SetValue(int(value))
    elif t == ps.intfIBoolean:
        ps.CBooleanPtr(node).SetValue(bool(value))
    else:
        raise CameraError(f"node {name!r} has an unsupported type for writing")


def _ip_from_int(value: Any) -> str | None:
    if value is None:
        return None
    v = int(value)
    return ".".join(str((v >> s) & 0xFF) for s in (24, 16, 8, 0))


def _mac_from_int(value: Any) -> str | None:
    if value is None:
        return None
    v = int(value)
    return ":".join(f"{(v >> s) & 0xFF:02x}" for s in (40, 32, 24, 16, 8, 0))


class SpinnakerCameraBackend(CameraBackend):
    """One camera connection through PySpin.

    Args:
        ir_format: temperature-linear format to configure on connect, or ``None`` to leave the
            camera exactly as found (read-only inspection).
        pixel_format: pixel format to configure when ``ir_format`` is not ``None``.
        buffer_handling: TL stream ``StreamBufferHandlingMode`` entry.
        buffer_count: TL stream ``StreamBufferCountManual``.
        grab_timeout_ms: ``GetNextImage`` timeout.
        restore_on_disconnect: put ``IRFormat``/``PixelFormat`` back to the as-found values.
    """

    def __init__(
        self,
        *,
        ir_format: IRFormat | None = IRFormat.TEMPERATURE_LINEAR_10MK,
        pixel_format: str = "Mono16",
        buffer_handling: str = "OldestFirst",
        buffer_count: int = 30,
        grab_timeout_ms: int = 2000,
        restore_on_disconnect: bool = True,
    ) -> None:
        self._ir_format = ir_format
        self._pixel_format = pixel_format
        self._buffer_handling = buffer_handling
        self._buffer_count = buffer_count
        self._grab_timeout_ms = grab_timeout_ms
        self._restore = restore_on_disconnect
        self._ps: Any = None
        self._system: Any = None
        self._cam_list: Any = None
        self._cam: Any = None
        self._nodemap: Any = None
        self._stream_nodemap: Any = None
        self._restore_values: list[tuple[str, str]] = []
        self._ir_format_before: str | None = None
        self._cases: list[dict[str, Any]] = []
        self._timestamp_offset_ns: int | None = None
        self._streaming = False
        self.incomplete_seen = 0

    # -- system lifecycle ---------------------------------------------------------------

    def _ensure_system(self) -> None:
        if self._system is None:
            self._ps = _pyspin()
            self._system = self._ps.System.GetInstance()

    def _release_system(self) -> None:
        if self._system is not None:
            try:
                self._system.ReleaseInstance()
            except Exception as exc:  # noqa: BLE001
                logger.error("Spinnaker ReleaseInstance failed: %s", exc)
            self._system = None

    def spinnaker_version(self) -> str:
        self._ensure_system()
        v = self._system.GetLibraryVersion()
        return f"{v.major}.{v.minor}.{v.type}.{v.build}"

    # -- CameraBackend -----------------------------------------------------------------

    def enumerate(self) -> list[DeviceDescriptor]:
        self._ensure_system()
        ps = self._ps
        cam_list = self._system.GetCameras()
        out: list[DeviceDescriptor] = []
        try:
            for i in range(cam_list.GetSize()):
                c = cam_list.GetByIndex(i)
                tl = c.GetTLDeviceNodeMap()
                out.append(
                    DeviceDescriptor(
                        backend="spinnaker",
                        model=str(_read(ps, tl, "DeviceModelName") or ""),
                        serial=str(_read(ps, tl, "DeviceSerialNumber") or ""),
                        ip_address=_ip_from_int(_read(ps, tl, "GevDeviceIPAddress")),
                        mac_address=_mac_from_int(_read(ps, tl, "GevDeviceMACAddress")),
                        firmware=_read(ps, tl, "DeviceVersion"),
                        interface=str(_read(ps, tl, "DeviceType") or "unknown"),
                    )
                )
                del c
        finally:
            cam_list.Clear()
        return out

    def connect(self, descriptor: DeviceDescriptor) -> None:
        if self._cam is not None:
            raise CameraError("already connected")
        self._ensure_system()
        ps = self._ps
        self._cam_list = self._system.GetCameras()
        cam = None
        try:
            for i in range(self._cam_list.GetSize()):
                c = self._cam_list.GetByIndex(i)
                if (
                    str(_read(ps, c.GetTLDeviceNodeMap(), "DeviceSerialNumber"))
                    == descriptor.serial
                ):
                    cam = c
                    break
                del c
            if cam is None:
                raise NotConnectedError(f"camera serial {descriptor.serial!r} not found")
            tl = cam.GetTLDeviceNodeMap()
            if _read(ps, tl, "GevDeviceIsWrongSubnet"):
                raise CameraError(
                    "camera is on a wrong subnet; fix the host adapter first (docs/camera_setup.md)"
                )
            cam.Init()
            self._cam = cam
            self._nodemap = cam.GetNodeMap()
            self._stream_nodemap = cam.GetTLStreamNodeMap()
            self._ir_format_before = _read(ps, self._nodemap, "IRFormat")
            self._configure()
            self._cases = self._enumerate_cases()
            self._timestamp_offset_ns = self._measure_timestamp_offset()
            logger.info(
                "connected %s %s ir_format=%s (was %s) case=%s",
                descriptor.model,
                descriptor.serial,
                _read(ps, self._nodemap, "IRFormat"),
                self._ir_format_before,
                _read(ps, self._nodemap, "CurrentCase"),
            )
        except (ps.SpinnakerException, CameraError) as exc:
            # Drop every SDK reference *before* re-raising: a traceback that still pins `cam`
            # (or a node pointer in a callee's frame) makes Spinnaker abort the whole process on
            # ReleaseInstance ("something still holds a reference to the camera", -1004).
            message = str(exc)
            is_camera_error = isinstance(exc, CameraError)
            traceback.clear_frames(exc.__traceback__)
            if self._cam is not None:  # Init() succeeded before the failure: undo it
                try:
                    self._cam.DeInit()
                except ps.SpinnakerException:
                    pass
            self._cam = None
            self._nodemap = None
            self._stream_nodemap = None
            cam = None
            c = None  # noqa: F841 - the loop variable still points at the matched camera
            tl = None  # noqa: F841 - deliberately clear the local
            self._cam_list.Clear()
            self._cam_list = None
            self._release_system()
            if is_camera_error:
                raise CameraError(message) from None
            raise CameraError(f"Spinnaker: {message}") from None

    def _stop_stale_acquisition(self) -> bool:
        """A previous owner that died (killed operator) can leave the camera streaming, which
        locks PixelFormat/IRFormat. Sending AcquisitionStop releases them. True if sent."""
        ps, nm = self._ps, self._nodemap
        try:
            node = nm.GetNode("AcquisitionStop")
            if node is None or not ps.IsWritable(node):
                return False
            ps.CCommandPtr(node).Execute()
            logger.warning("camera was still streaming for a previous owner; sent AcquisitionStop")
            return True
        except ps.SpinnakerException as exc:
            logger.warning("AcquisitionStop failed: %s", exc)
            return False

    def _configure(self) -> None:
        ps, nm = self._ps, self._nodemap
        if self._ir_format is not None:
            try:
                prev = _set_enum(ps, nm, "PixelFormat", self._pixel_format)
            except CameraError:
                if not self._stop_stale_acquisition():
                    raise
                time.sleep(0.3)
                prev = _set_enum(ps, nm, "PixelFormat", self._pixel_format)
            if prev != self._pixel_format:
                self._restore_values.append(("PixelFormat", prev))
            prev = _set_enum(ps, nm, "IRFormat", self._ir_format.value)
            if prev != self._ir_format.value:
                self._restore_values.append(("IRFormat", prev))
        snm = self._stream_nodemap
        try:
            _set_enum(ps, snm, "StreamBufferHandlingMode", self._buffer_handling)
            count = ps.CIntegerPtr(snm.GetNode("StreamBufferCountManual"))
            if ps.IsWritable(count):
                count.SetValue(
                    max(int(count.GetMin()), min(self._buffer_count, int(count.GetMax())))
                )
        except (ps.SpinnakerException, CameraError) as exc:
            logger.warning("stream buffer configuration skipped: %s", exc)

    def _enumerate_cases(self) -> list[dict[str, Any]]:
        ps, nm = self._ps, self._nodemap
        n = _read(ps, nm, "NumCases")
        query = nm.GetNode("QueryCase")
        if not n or query is None or not ps.IsWritable(query):
            return []
        q = ps.CIntegerPtr(query)
        original = int(q.GetValue())
        cases: list[dict[str, Any]] = []
        try:
            for i in range(int(n)):
                q.SetValue(i)
                cases.append(
                    {
                        "index": i,
                        "low_k": _read(ps, nm, "QueryCaseLowLimit"),
                        "high_k": _read(ps, nm, "QueryCaseHighLimit"),
                        "enabled": _read(ps, nm, "QueryCaseEnabled"),
                    }
                )
        finally:
            q.SetValue(original)
        return cases

    def _measure_timestamp_offset(self) -> int | None:
        """camera_time - host_time in ns via TimestampLatch (host time taken mid-latch)."""
        ps, nm = self._ps, self._nodemap
        try:
            latch = nm.GetNode("TimestampLatch")
            if latch is None or not ps.IsWritable(latch):
                return None
            t0 = time.time_ns()
            ps.CCommandPtr(latch).Execute()
            t1 = time.time_ns()
            cam_ns = _read(ps, nm, "TimestampLatchValue")
            return int(cam_ns) - (t0 + t1) // 2 if cam_ns is not None else None
        except ps.SpinnakerException:
            return None

    def disconnect(self) -> None:
        ps = self._ps
        if self._cam is not None:
            try:
                if self._streaming:
                    self._cam.EndAcquisition()
                    self._streaming = False
                if self._restore:
                    for name, previous in reversed(self._restore_values):
                        try:
                            _set_enum(ps, self._nodemap, name, previous)
                            logger.info("restored %s=%s", name, previous)
                        except (ps.SpinnakerException, CameraError) as exc:
                            logger.error("failed to restore %s=%s: %s", name, previous, exc)
                self._restore_values = []
                if self._cam.IsInitialized():
                    self._cam.DeInit()
            except ps.SpinnakerException as exc:
                logger.error("disconnect: %s", exc)
            finally:
                self._nodemap = None
                self._stream_nodemap = None
                self._cam = None
        if self._cam_list is not None:
            self._cam_list.Clear()
            self._cam_list = None
        self._release_system()

    @property
    def is_connected(self) -> bool:
        return self._cam is not None

    def read_node(self, name: str) -> Any:
        """Read one node by name (None if absent). For diagnostics/UI; not for hot paths."""
        self._require_connected()
        return _read(self._ps, self._nodemap, name)

    def camera_info(self) -> dict[str, Any]:
        self._require_connected()
        ps, nm = self._ps, self._nodemap
        names = (
            IDENTITY_NODES + ACQUISITION_NODES + OBJECT_PARAMETER_NODES + CALIBRATION_CONSTANT_NODES
        )
        raw = {n: _read(ps, nm, n) for n in names}
        info = build_camera_info(
            raw,
            cases=self._cases,
            spinnaker_version=self.spinnaker_version(),
            ir_format_before=self._ir_format_before,
            timestamp_offset_ns=self._timestamp_offset_ns,
        )
        info["enum_options"] = {n: _enum_entries(ps, nm, n) for n in ENUM_NODES}
        info["nuc_count"] = self._nuc_count
        return info

    # -- controls (brief §30) ------------------------------------------------------------

    _nuc_count = 0

    def set_parameters(self, values: dict[str, Any]) -> dict[str, Any]:
        self._require_connected()
        ps, nm = self._ps, self._nodemap
        clean = validate_values(
            values,
            enum_options={n: _enum_entries(ps, nm, n) for n in ENUM_NODES},
            n_cases=len(self._cases),
        )
        try:
            for name, v in clean.items():
                _write(ps, nm, name, v)
        except ps.SpinnakerException as exc:
            raise CameraError(f"camera rejected the write: {exc}") from exc
        logger.info("camera parameters written: %s", clean)
        return {name: _read(ps, nm, name) for name in clean}

    def execute(self, command: str) -> None:
        self._require_connected()
        if command not in COMMANDS:
            raise ValueError(f"unknown command {command!r}")
        ps, nm = self._ps, self._nodemap
        node = nm.GetNode(command)
        if node is None or not ps.IsWritable(node):
            raise CameraError(f"command {command!r} is not available")
        try:
            ps.CCommandPtr(node).Execute()
        except ps.SpinnakerException as exc:
            raise CameraError(f"command {command!r} failed: {exc}") from exc
        self._nuc_count += 1
        logger.info("camera command executed: %s", command)

    def stream_stats(self) -> dict[str, Any]:
        """Transport-layer frame/packet counters (valid while or right after streaming)."""
        self._require_connected()
        out = {k: _read(self._ps, self._stream_nodemap, n) for k, n in STREAM_COUNTER_NODES.items()}
        out["incomplete_seen_by_app"] = self.incomplete_seen
        return out

    def frames(self) -> Iterator[Frame]:
        self._require_connected()
        ps, cam = self._ps, self._cam
        pixel_format = str(_read(ps, self._nodemap, "PixelFormat"))
        ir_format = str(_read(ps, self._nodemap, "IRFormat"))
        try:
            cam.BeginAcquisition()
            self._streaming = True
            while self._cam is not None:
                image = cam.GetNextImage(self._grab_timeout_ms)
                try:
                    host_ns = time.time_ns()
                    if image.IsIncomplete():
                        self.incomplete_seen += 1
                        logger.warning(
                            "incomplete frame id=%s status=%s",
                            image.GetFrameID(),
                            image.GetImageStatus(),
                        )
                        continue
                    data = np.array(image.GetNDArray(), copy=True)
                    if data.dtype != np.uint16:
                        raise CameraError(f"unexpected pixel dtype {data.dtype}; expected uint16")
                    frame = Frame(
                        frame_id=int(image.GetFrameID()),
                        device_timestamp_ns=int(image.GetTimeStamp()),
                        host_timestamp_ns=host_ns,
                        pixel_format=pixel_format,
                        ir_format=ir_format,
                        counts=data,
                        incomplete=False,
                    )
                finally:
                    image.Release()
                yield frame
        except ps.SpinnakerException as exc:
            raise CameraError(f"Spinnaker: {exc}") from None
        finally:
            if self._streaming and self._cam is not None:
                try:
                    cam.EndAcquisition()
                except ps.SpinnakerException as exc:
                    logger.error("EndAcquisition: %s", exc)
            self._streaming = False

    def _require_connected(self) -> None:
        if self._cam is None:
            raise NotConnectedError("Spinnaker camera is not connected")


__all__ = [
    "ACQUISITION_NODES",
    "CALIBRATION_CONSTANT_NODES",
    "IDENTITY_NODES",
    "OBJECT_PARAMETER_NODES",
    "STREAM_COUNTER_NODES",
    "SpinnakerCameraBackend",
    "build_camera_info",
]
