"""Milestone-1 camera probe.

Purpose: discover what THIS camera exposes through Spinnaker/GenICam and acquire ONE frame,
without assuming radiometric node names from other FLIR models. The probe is intentionally
read-only: it does not change camera settings unless ``--set-temperature-linear`` is given,
and then it restores the previous values before exiting.

Two modes:

* ``--simulated``  runs the same report pipeline against :class:`SimulatedCameraBackend`
  (no PySpin needed) so the report format can be exercised in CI.
* default          imports PySpin lazily and probes the first (or ``--serial``-selected)
  camera, dumping the full GenICam node maps to JSON.

Everything PySpin-specific lives in this module and ``camera/spinnaker.py``; nothing else in
the package imports PySpin.
"""

from __future__ import annotations

import argparse
import json
import logging
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from flir_research_interface import __version__
from flir_research_interface.camera.simulated import HotspotRampScene, SimulatedCameraBackend
from flir_research_interface.radiometry.temperature_linear import (
    IRFormat,
    counts_to_celsius,
    kelvin_per_count,
)

logger = logging.getLogger(__name__)

PROBE_VERSION = "1"

RADIOMETRY_KEYWORDS: tuple[str, ...] = (
    # Heuristic filter ONLY, used to highlight candidate nodes in the dump. The full node map
    # is always saved; this list never decides what the application uses.
    "IRFormat",
    "Radiometr",
    "TemperatureLinear",
    "Emiss",
    "Reflected",
    "Atmospher",
    "Humidity",
    "ObjectDistance",
    "Distance",
    "ExtOptics",
    "Transmission",
    "NUC",
    "Nuc",
    "Calibrat",
    "Case",
    "Range",
    "Temperature",
    "Thermal",
    "Sensor",
    "Palette",
    "Shutter",
    "Focus",
    "Timestamp",
    "Ptp",
    "PTP",
    "Gev",
    "Chunk",
)

_GENERIC_EXCLUDE: tuple[str, ...] = (
    "Width",
    "Height",
    "OffsetX",
    "OffsetY",
    "PixelFormat",
    "AcquisitionMode",
    "GevSCPSPacketSize",
)


def is_radiometry_related(node_name: str) -> bool:
    """True if ``node_name`` matches a radiometry/thermal keyword (heuristic highlight only)."""
    if node_name in _GENERIC_EXCLUDE:
        return False
    return any(k.lower() in node_name.lower() for k in RADIOMETRY_KEYWORDS)


def summarize_counts(counts: npt.NDArray[np.uint16]) -> dict[str, Any]:
    """Min/max/center statistics of a raw count array (no unit interpretation)."""
    h, w = counts.shape
    cx, cy = w // 2, h // 2
    return {
        "width": int(w),
        "height": int(h),
        "dtype": str(counts.dtype),
        "min": int(counts.min()),
        "max": int(counts.max()),
        "mean": float(counts.mean()),
        "center_xy": [cx, cy],
        "center_value": int(counts[cy, cx]),
    }


def host_info() -> dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "numpy": np.__version__,
        "app_version": __version__,
        "utc": datetime.now(timezone.utc).isoformat(),
    }


def _derived_temperature_fields(
    counts: npt.NDArray[np.uint16], ir_format: str | None
) -> dict[str, Any]:
    """Attach a labelled, derived temperature only when the IRFormat is temperature-linear."""
    try:
        fmt = IRFormat(ir_format) if ir_format else None
        scale = kelvin_per_count(fmt) if fmt else None
    except ValueError:
        fmt, scale = None, None
    if fmt is None or scale is None:
        return {
            "counts_to_celsius_rule": None,
            "center_temperature_c": None,
            "note": "No temperature conversion applied: IRFormat is not a documented "
            "temperature-linear format (or is unknown). Values above are raw counts.",
        }
    celsius = counts_to_celsius(counts, fmt)
    h, w = counts.shape
    return {
        "counts_to_celsius_rule": f"T_C = counts * {scale} - 273.15  (IRFormat={fmt.value})",
        "center_temperature_c": float(celsius[h // 2, w // 2]),
        "min_temperature_c": float(celsius.min()),
        "max_temperature_c": float(celsius.max()),
    }


# --------------------------------------------------------------------------------------
# Simulated path
# --------------------------------------------------------------------------------------


def run_simulated_probe() -> dict[str, Any]:
    """Probe the simulated backend; same report layout as the hardware probe."""
    scene = HotspotRampScene(
        background_c=25.0,
        start_c=25.0,
        end_c=200.0,
        ramp_s=60.0,
        center_xy=(320, 240),
        radius_px=40,
    )
    cam = SimulatedCameraBackend(scene=scene)
    devices = cam.enumerate()
    cam.connect(devices[0])
    try:
        frame = next(cam.frames())
        info = cam.camera_info()
    finally:
        cam.disconnect()
    frame_report: dict[str, Any] = {
        "frame_id": frame.frame_id,
        "device_timestamp_ns": frame.device_timestamp_ns,
        "host_timestamp_ns": frame.host_timestamp_ns,
        "pixel_format": frame.pixel_format,
        "ir_format": frame.ir_format,
        "incomplete": frame.incomplete,
        **summarize_counts(frame.counts),
        **_derived_temperature_fields(frame.counts, frame.ir_format),
    }
    return {
        "probe_version": PROBE_VERSION,
        "host": host_info(),
        "backend": "simulated",
        "device": devices[0].__dict__,
        "camera_info": info,
        "frame": frame_report,
    }


# --------------------------------------------------------------------------------------
# PySpin path (hardware). Imported lazily.
# --------------------------------------------------------------------------------------


def _node_to_dict(pyspin: Any, node: Any) -> dict[str, Any]:  # noqa: C901 - flat dispatcher
    """Serialize one GenICam node generically. Never raises; errors are recorded."""
    out: dict[str, Any] = {"name": node.GetName()}
    try:
        out["display_name"] = node.GetDisplayName()
        out["readable"] = bool(pyspin.IsReadable(node))
        out["writable"] = bool(pyspin.IsWritable(node))
        out["available"] = bool(pyspin.IsAvailable(node))
        try:
            out["description"] = node.GetDescription()
        except Exception:  # noqa: BLE001 - optional metadata
            pass
        itype = node.GetPrincipalInterfaceType()
        if itype == pyspin.intfIInteger:
            n = pyspin.CIntegerPtr(node)
            out["type"] = "integer"
            if out["readable"]:
                out["value"] = int(n.GetValue())
                out["min"], out["max"] = int(n.GetMin()), int(n.GetMax())
                out["unit"] = n.GetUnit()
        elif itype == pyspin.intfIFloat:
            n = pyspin.CFloatPtr(node)
            out["type"] = "float"
            if out["readable"]:
                out["value"] = float(n.GetValue())
                out["min"], out["max"] = float(n.GetMin()), float(n.GetMax())
                out["unit"] = n.GetUnit()
        elif itype == pyspin.intfIBoolean:
            out["type"] = "boolean"
            if out["readable"]:
                out["value"] = bool(pyspin.CBooleanPtr(node).GetValue())
        elif itype == pyspin.intfIString:
            out["type"] = "string"
            if out["readable"]:
                out["value"] = str(pyspin.CStringPtr(node).GetValue())
        elif itype == pyspin.intfIEnumeration:
            n = pyspin.CEnumerationPtr(node)
            out["type"] = "enumeration"
            entries = []
            for e in n.GetEntries():
                ee = pyspin.CEnumEntryPtr(e)
                entries.append(
                    {
                        "symbolic": ee.GetSymbolic(),
                        "available": bool(pyspin.IsAvailable(ee)),
                        "readable": bool(pyspin.IsReadable(ee)),
                    }
                )
            out["entries"] = entries
            if out["readable"]:
                out["value"] = pyspin.CEnumEntryPtr(n.GetCurrentEntry()).GetSymbolic()
        elif itype == pyspin.intfICommand:
            out["type"] = "command"
        elif itype == pyspin.intfICategory:
            out["type"] = "category"
        elif itype == pyspin.intfIRegister:
            out["type"] = "register"
        else:
            out["type"] = f"other({itype})"
    except Exception as exc:  # noqa: BLE001 - we want the dump to survive any node
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def _walk_nodemap(pyspin: Any, nodemap: Any) -> list[dict[str, Any]]:
    """Depth-first walk from the Root category; returns a flat list of node dicts."""
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(node: Any, path: str) -> None:
        name = node.GetName()
        if name in seen:
            return
        seen.add(name)
        d = _node_to_dict(pyspin, node)
        d["path"] = path
        result.append(d)
        if d.get("type") == "category":
            try:
                for child in pyspin.CCategoryPtr(node).GetFeatures():
                    visit(child, f"{path}/{name}")
            except Exception as exc:  # noqa: BLE001
                d["children_error"] = f"{type(exc).__name__}: {exc}"

    root = nodemap.GetNode("Root")
    if root is None or not pyspin.IsAvailable(root):
        return result
    visit(root, "")
    return result


def _read_str(pyspin: Any, nodemap: Any, name: str) -> str | None:
    try:
        node = nodemap.GetNode(name)
        if node is None or not pyspin.IsReadable(node):
            return None
        itype = node.GetPrincipalInterfaceType()
        if itype == pyspin.intfIEnumeration:
            return str(
                pyspin.CEnumEntryPtr(pyspin.CEnumerationPtr(node).GetCurrentEntry()).GetSymbolic()
            )
        if itype == pyspin.intfIInteger:
            return str(pyspin.CIntegerPtr(node).GetValue())
        return str(pyspin.CValuePtr(node).ToString())
    except Exception:  # noqa: BLE001
        return None


def _set_enum(pyspin: Any, nodemap: Any, name: str, symbolic: str) -> str | None:
    """Set enumeration ``name`` to ``symbolic``; return the previous symbolic value."""
    node = pyspin.CEnumerationPtr(nodemap.GetNode(name))
    if not pyspin.IsWritable(node):
        raise RuntimeError(f"node {name!r} is not writable")
    previous = pyspin.CEnumEntryPtr(node.GetCurrentEntry()).GetSymbolic()
    entry = pyspin.CEnumEntryPtr(node.GetEntryByName(symbolic))
    if not pyspin.IsReadable(entry):
        raise RuntimeError(f"entry {symbolic!r} not available on node {name!r}")
    node.SetIntValue(entry.GetValue())
    return str(previous)


def _ip_from_int(value: str | None) -> str | None:
    try:
        v = int(value) if value is not None else None
    except ValueError:
        return value
    if v is None:
        return None
    return ".".join(str((v >> shift) & 0xFF) for shift in (24, 16, 8, 0))


def run_hardware_probe(
    *, serial: str | None, output_dir: Path, set_temperature_linear: bool, grab_timeout_ms: int
) -> dict[str, Any]:
    """Probe a real camera through PySpin. Follows FLIR example ordering for cleanup."""
    try:
        import PySpin as pyspin  # noqa: N813
    except ImportError as exc:
        raise SystemExit(
            "PySpin is not importable in this interpreter. Install the Spinnaker SDK and the "
            "matching spinnaker_python wheel (see docs/installation.md), or run with --simulated."
        ) from exc

    report: dict[str, Any] = {
        "probe_version": PROBE_VERSION,
        "host": host_info(),
        "backend": "spinnaker",
    }
    system = pyspin.System.GetInstance()
    cam = None
    cam_list = None
    restore: list[tuple[str, str]] = []
    acquiring = False
    try:
        v = system.GetLibraryVersion()
        report["spinnaker_version"] = f"{v.major}.{v.minor}.{v.type}.{v.build}"
        logger.info("Spinnaker library %s", report["spinnaker_version"])

        cam_list = system.GetCameras()
        devices: list[dict[str, Any]] = []
        for i in range(cam_list.GetSize()):
            c = cam_list.GetByIndex(i)
            tl = c.GetTLDeviceNodeMap()
            devices.append(
                {
                    "index": i,
                    "vendor": _read_str(pyspin, tl, "DeviceVendorName"),
                    "model": _read_str(pyspin, tl, "DeviceModelName"),
                    "serial": _read_str(pyspin, tl, "DeviceSerialNumber"),
                    "firmware": _read_str(pyspin, tl, "DeviceVersion"),
                    "device_type": _read_str(pyspin, tl, "DeviceType"),
                    "ip_address": _ip_from_int(_read_str(pyspin, tl, "GevDeviceIPAddress")),
                    "mac_address": _read_str(pyspin, tl, "GevDeviceMACAddress"),
                    "access_status": _read_str(pyspin, tl, "DeviceAccessStatus"),
                }
            )
            del c
        report["devices"] = devices
        logger.info("Cameras detected: %d", len(devices))
        for d in devices:
            logger.info(
                "  [%d] %s %s serial=%s ip=%s fw=%s",
                d["index"],
                d["vendor"],
                d["model"],
                d["serial"],
                d["ip_address"],
                d["firmware"],
            )
        if not devices:
            report["error"] = "no cameras detected"
            return report

        chosen = 0
        if serial is not None:
            matches = [d["index"] for d in devices if d["serial"] == serial]
            if not matches:
                raise SystemExit(f"no camera with serial {serial!r}")
            chosen = int(matches[0])
        report["device"] = devices[chosen]

        cam = cam_list.GetByIndex(chosen)
        cam.Init()
        nodemap = cam.GetNodeMap()
        tl_device = cam.GetTLDeviceNodeMap()
        tl_stream = cam.GetTLStreamNodeMap()

        logger.info("Dumping node maps (device / TL device / TL stream) ...")
        report["nodemaps"] = {
            "device": _walk_nodemap(pyspin, nodemap),
            "tl_device": _walk_nodemap(pyspin, tl_device),
            "tl_stream": _walk_nodemap(pyspin, tl_stream),
        }
        report["radiometry_candidates"] = [
            n for n in report["nodemaps"]["device"] if is_radiometry_related(n["name"])
        ]
        logger.info(
            "Device node map: %d nodes; %d radiometry-keyword candidates",
            len(report["nodemaps"]["device"]),
            len(report["radiometry_candidates"]),
        )

        basics = {}
        for name in (
            "Width",
            "Height",
            "WidthMax",
            "HeightMax",
            "SensorWidth",
            "SensorHeight",
            "PixelFormat",
            "IRFormat",
            "AcquisitionMode",
            "AcquisitionFrameRate",
            "DeviceTemperature",
            "GevTimestampTickFrequency",
            "TimestampLatchValue",
            "GevTimestampValue",
        ):
            basics[name] = _read_str(pyspin, nodemap, name)
        report["basics_before"] = basics

        if set_temperature_linear:
            logger.warning(
                "Setting PixelFormat=Mono16 and IRFormat=TemperatureLinear10mK (will restore)"
            )
            prev = _set_enum(pyspin, nodemap, "PixelFormat", "Mono16")
            if prev is not None:
                restore.append(("PixelFormat", prev))
            prev = _set_enum(pyspin, nodemap, "IRFormat", "TemperatureLinear10mK")
            if prev is not None:
                restore.append(("IRFormat", prev))
            report["settings_changed"] = [{"node": n, "previous": p} for n, p in restore]

        # Timestamp latch attempts (both generations of node names; whichever exists).
        latches: dict[str, Any] = {}
        for cmd, val in (
            ("TimestampLatch", "TimestampLatchValue"),
            ("GevTimestampControlLatch", "GevTimestampValue"),
        ):
            try:
                node = nodemap.GetNode(cmd)
                if node is not None and pyspin.IsWritable(node):
                    host_before = time.time_ns()
                    pyspin.CCommandPtr(node).Execute()
                    host_after = time.time_ns()
                    latches[cmd] = {
                        "camera_value": _read_str(pyspin, nodemap, val),
                        "host_ns_before": host_before,
                        "host_ns_after": host_after,
                    }
            except Exception as exc:  # noqa: BLE001
                latches[cmd] = {"error": f"{type(exc).__name__}: {exc}"}
        report["timestamp_latch"] = latches

        logger.info("Acquiring one frame ...")
        cam.BeginAcquisition()
        acquiring = True
        image = cam.GetNextImage(grab_timeout_ms)
        try:
            host_ns = time.time_ns()
            frame_report: dict[str, Any] = {
                "host_timestamp_ns": host_ns,
                "incomplete": bool(image.IsIncomplete()),
                "image_status": int(image.GetImageStatus()),
                "frame_id": int(image.GetFrameID()),
                "device_timestamp_ns": int(image.GetTimeStamp()),
                "width": int(image.GetWidth()),
                "height": int(image.GetHeight()),
                "pixel_format": str(image.GetPixelFormatName()),
                "bits_per_pixel": int(image.GetBitsPerPixel()),
                "ir_format": _read_str(pyspin, nodemap, "IRFormat"),
            }
            if not frame_report["incomplete"]:
                data = np.array(image.GetNDArray(), copy=True)  # copy BEFORE Release
                frame_report["ndarray_dtype"] = str(data.dtype)
                frame_report["ndarray_shape"] = list(data.shape)
                if data.dtype == np.uint16 and data.ndim == 2:
                    frame_report.update(summarize_counts(data))
                    frame_report.update(
                        _derived_temperature_fields(data, frame_report["ir_format"])
                    )
                else:
                    frame_report["note"] = "frame is not 2-D uint16; no count statistics computed"
                output_dir.mkdir(parents=True, exist_ok=True)
                np.save(output_dir / "frame_raw.npy", data)
                frame_report["saved_raw"] = str(output_dir / "frame_raw.npy")
        finally:
            image.Release()
        report["frame"] = frame_report
        return report
    finally:
        try:
            if cam is not None:
                if acquiring:
                    cam.EndAcquisition()
                for name, previous in reversed(restore):
                    try:
                        _set_enum(pyspin, cam.GetNodeMap(), name, previous)
                        logger.info("Restored %s=%s", name, previous)
                    except Exception as exc:  # noqa: BLE001
                        logger.error("Failed to restore %s=%s: %s", name, previous, exc)
                if cam.IsInitialized():
                    cam.DeInit()
                del cam
            if cam_list is not None:
                cam_list.Clear()
        finally:
            system.ReleaseInstance()
            logger.info("Spinnaker released")


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def _print_summary(report: dict[str, Any]) -> None:
    dev = report.get("device", {})
    print("=" * 72)
    print(f"FLIR Research Interface probe v{PROBE_VERSION}  backend={report['backend']}")
    if "spinnaker_version" in report:
        print(f"Spinnaker: {report['spinnaker_version']}")
    print(f"Device: {dev}")
    if "basics_before" in report:
        print("Basics:", json.dumps(report["basics_before"], indent=2))
    if "radiometry_candidates" in report:
        print(f"Radiometry-keyword candidate nodes ({len(report['radiometry_candidates'])}):")
        for n in report["radiometry_candidates"]:
            val = n.get("value")
            entries = [e["symbolic"] for e in n.get("entries", [])] if "entries" in n else None
            print(
                f"  {n['name']:<40} {n.get('type', '?'):<12} value={val!r}"
                + (f" entries={entries}" if entries else "")
            )
    if "timestamp_latch" in report:
        print("Timestamp latch:", json.dumps(report["timestamp_latch"], indent=2))
    if "frame" in report:
        print("Frame:", json.dumps(report["frame"], indent=2))
    if "error" in report:
        print("ERROR:", report["error"])
    print("=" * 72)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FLIR Research Interface Milestone-1 camera probe")
    parser.add_argument("--simulated", action="store_true", help="probe the simulated backend")
    parser.add_argument("--serial", default=None, help="select camera by serial number")
    parser.add_argument("--output-dir", default=None, help="where to write probe JSON + raw frame")
    parser.add_argument(
        "--set-temperature-linear",
        action="store_true",
        help="TEMPORARILY set PixelFormat=Mono16, IRFormat=TemperatureLinear10mK "
        "(restored on exit). Default is read-only.",
    )
    parser.add_argument("--timeout-ms", type=int, default=5000, help="GetNextImage timeout")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) if args.output_dir else Path(f"probe_output_{stamp}")

    if args.simulated:
        report = run_simulated_probe()
    else:
        report = run_hardware_probe(
            serial=args.serial,
            output_dir=output_dir,
            set_temperature_linear=args.set_temperature_linear,
            grab_timeout_ms=args.timeout_ms,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / "probe_report.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    _print_summary(report)
    print(f"Full report written to {out}")
    return 0 if "error" not in report else 1


if __name__ == "__main__":
    raise SystemExit(main())
