"""Named presets: visible adjustment + thermal camera settings + thermal display settings.

Stored on the operator in ``<experiments_root>/../calibration/presets.json`` (see
``analysis.calibration.calibration_dir``)::

    {"version": 1, "last_applied": "name" | null,
     "presets": [{"name", "visible_adjust", "thermal", "display", "saved_utc"}]}

``thermal`` holds only :data:`camera.controls.WRITABLE_NODES` in the camera's own units. This
module never talks to a camera: applying a preset is the browser's job, through the camera-control
routes. Reads are tolerant (a missing or damaged file reads as no presets, with a warning) and
writes are atomic (temp file + ``os.replace``). Before a save overwrites a file that could not be
read, that file is copied to ``presets.json.corrupt`` so the operator's old presets are not lost
silently.
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import tempfile
import threading
import unicodedata
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flir_research_interface.analysis.calibration import calibration_dir
from flir_research_interface.analysis.visible_adjust import validate_adjust
from flir_research_interface.camera.controls import (
    ENUM_NODES,
    FLOAT_NODES,
    INT_NODES,
    WRITABLE_NODES,
    validate_values,
)

logger = logging.getLogger(__name__)

PRESETS_FILE = "presets.json"
VERSION = 1
MAX_NAME_LEN = 60
MAX_PALETTE_LEN = 40
_LOCK = threading.Lock()  # the routes run in a thread pool; every change is read-modify-write


class PresetNotFoundError(KeyError):
    """No preset has the given name."""


class PresetExistsError(ValueError):
    """A preset with the new name already exists."""


def _empty() -> dict[str, Any]:
    return {"version": VERSION, "last_applied": None, "presets": []}


def normalize_name(raw: Any) -> str:
    """Strip ``raw`` and check it: 1-60 characters, no ``/`` or ``\\``, no control characters."""
    if not isinstance(raw, str):
        raise ValueError("preset name must be text")
    name = raw.strip()
    if not 1 <= len(name) <= MAX_NAME_LEN:
        raise ValueError(f"preset name must be 1-{MAX_NAME_LEN} characters")
    if "/" in name or "\\" in name:
        raise ValueError("preset name must not contain / or \\")
    if any(unicodedata.category(ch).startswith("C") for ch in name):
        raise ValueError("preset name must not contain control characters")
    return name


def _finite(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


def _validate_display(raw: Any) -> dict[str, Any]:
    """``{palette, range}``. The palette is any non-empty string up to 40 characters: the
    frontend's palette list (``frontend/src/lib/palette.ts``) is not the backend's
    (``analysis/palettes.py``), so neither can be the authority here."""
    if not isinstance(raw, Mapping):
        raise ValueError("display must be an object")
    palette = raw.get("palette")
    if not isinstance(palette, str) or not 1 <= len(palette.strip()) <= MAX_PALETTE_LEN:
        raise ValueError(
            f"display.palette must be a non-empty string up to {MAX_PALETTE_LEN} characters"
        )
    rng = raw.get("range")
    if not isinstance(rng, Mapping):
        raise ValueError("display.range must be an object")
    if rng.get("mode") == "auto":
        return {"palette": palette.strip(), "range": {"mode": "auto"}}
    if rng.get("mode") != "locked":
        raise ValueError('display.range.mode must be "auto" or "locked"')
    lo, hi = rng.get("min_c"), rng.get("max_c")
    if lo is None or hi is None or not _finite(lo) or not _finite(hi):
        raise ValueError("a locked display range needs finite min_c and max_c")
    if not lo < hi:
        raise ValueError("display.range.min_c must be below max_c")
    return {
        "palette": palette.strip(),
        "range": {"mode": "locked", "min_c": float(lo), "max_c": float(hi)},
    }


def _validate_thermal(
    raw: Any, enum_options: dict[str, list[str]] | None, n_cases: int | None
) -> dict[str, Any]:
    """Unknown nodes are always refused. With ``enum_options`` (a camera is connected) enum values
    must be among the camera's options and ``CurrentCase`` below ``n_cases``. Without, enum values
    only have to be non-empty text and ``CurrentCase`` a non-negative integer; the rest is checked
    when the preset is applied."""
    if not isinstance(raw, Mapping):
        raise ValueError("thermal must be an object")
    for name in raw:
        if name not in WRITABLE_NODES:
            raise ValueError(f"{name} is not a writable camera parameter")
    if enum_options is not None:
        cases = n_cases if n_cases is not None else 0
        return validate_values(dict(raw), enum_options=enum_options, n_cases=cases)
    values = dict(raw)
    for name in ENUM_NODES:
        if name in values and (not isinstance(values[name], str) or not values[name]):
            raise ValueError(f"{name} must be a non-empty string")
    for name in INT_NODES:
        if name not in values:
            continue
        v = values[name]
        whole = isinstance(v, int | float) and not isinstance(v, bool) and float(v).is_integer()
        if not whole or v < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    numeric = {k: v for k, v in values.items() if k in FLOAT_NODES}
    out = validate_values(numeric, enum_options={}, n_cases=0)
    for name in INT_NODES:
        if name in values:
            out[name] = int(values[name])
    for name in ENUM_NODES:
        if name in values:
            out[name] = values[name]
    return {k: out[k] for k in WRITABLE_NODES if k in out}


def validate_preset(
    preset: Any, *, enum_options: dict[str, list[str]] | None, n_cases: int | None
) -> dict[str, Any]:
    """Return the normalised preset (without ``saved_utc``) or raise ``ValueError``."""
    if not isinstance(preset, Mapping):
        raise ValueError("preset must be an object")
    return {
        "name": normalize_name(preset.get("name")),
        "visible_adjust": validate_adjust(preset.get("visible_adjust")),
        "thermal": _validate_thermal(preset.get("thermal", {}), enum_options, n_cases),
        "display": _validate_display(preset.get("display")),
    }


def _is_entry(e: Any) -> bool:
    return (
        isinstance(e, dict)
        and isinstance(e.get("name"), str) and bool(e["name"])
        and isinstance(e.get("visible_adjust"), dict)
        and isinstance(e.get("thermal"), dict)
        and isinstance(e.get("display"), dict)
    )


def _read(root: Path) -> tuple[dict[str, Any], bool]:
    """``(document, damaged)``. ``damaged`` means the file existed but could not be read whole."""
    path = calibration_dir(root) / PRESETS_FILE
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return _empty(), False
    except OSError as exc:
        logger.warning("cannot read %s (%s); reading as no presets", path, exc)
        return _empty(), True
    try:
        data = json.loads(raw)
    except ValueError as exc:
        logger.warning("%s is not valid JSON (%s); reading as no presets", path, exc)
        return _empty(), True
    if not isinstance(data, dict) or not isinstance(data.get("presets"), list):
        logger.warning("%s has an unexpected shape; reading as no presets", path)
        return _empty(), True
    entries = [e for e in data["presets"] if _is_entry(e)]
    damaged = len(entries) != len(data["presets"])
    if damaged:
        dropped = len(data["presets"]) - len(entries)
        logger.warning("%s: dropped %d malformed preset(s)", path, dropped)
    last = data.get("last_applied")
    names = {e["name"] for e in entries}
    return {
        "version": VERSION,
        "last_applied": last if isinstance(last, str) and last in names else None,
        "presets": entries,
    }, damaged


def _write(root: Path, doc: dict[str, Any], *, damaged: bool) -> None:
    d = calibration_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / PRESETS_FILE
    if damaged and path.is_file():
        aside = d / (PRESETS_FILE + ".corrupt")
        shutil.copy2(path, aside)
        logger.warning("kept the unreadable %s as %s before saving", path, aside)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".presets-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f, indent=2)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)  # no-op after a successful replace


def load_presets(root: Path) -> dict[str, Any]:
    """``{"version", "last_applied", "presets"}``; empty when the file is missing or unreadable.
    ``last_applied`` is ``None`` unless it names a stored preset."""
    return _read(Path(root))[0]


def save_preset(
    root: Path,
    preset: dict[str, Any],
    *,
    enum_options: dict[str, list[str]] | None,
    n_cases: int | None,
) -> dict[str, Any]:
    """Validate and store ``preset`` (replacing the one of the same name, in place); return the
    stored preset. Raises ``ValueError`` with nothing written when it is invalid. ``saved_utc`` is
    set here; any value in ``preset`` is ignored."""
    clean = validate_preset(preset, enum_options=enum_options, n_cases=n_cases)
    clean["saved_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _LOCK:
        doc, damaged = _read(Path(root))
        names = [p["name"] for p in doc["presets"]]
        if clean["name"] in names:
            doc["presets"][names.index(clean["name"])] = clean
        else:
            doc["presets"].append(clean)
        _write(Path(root), doc, damaged=damaged)
    return clean


def delete_preset(root: Path, name: str) -> None:
    """Remove ``name`` (clearing ``last_applied`` if it pointed there). ``PresetNotFoundError``."""
    with _LOCK:
        doc, damaged = _read(Path(root))
        kept = [p for p in doc["presets"] if p["name"] != name]
        if len(kept) == len(doc["presets"]):
            raise PresetNotFoundError(name)
        doc["presets"] = kept
        if doc["last_applied"] == name:
            doc["last_applied"] = None
        _write(Path(root), doc, damaged=damaged)


def rename_preset(root: Path, old: str, new: str) -> None:
    """Rename ``old`` to ``new``, keeping its place and ``last_applied``.

    Raises ``PresetNotFoundError`` for a missing ``old``, ``PresetExistsError`` when ``new`` is
    taken, ``ValueError`` for a bad name."""
    new_name = normalize_name(new)
    with _LOCK:
        doc, damaged = _read(Path(root))
        names = [p["name"] for p in doc["presets"]]
        if old not in names:
            raise PresetNotFoundError(old)
        if new_name != old and new_name in names:
            raise PresetExistsError(new_name)
        doc["presets"][names.index(old)] = {**doc["presets"][names.index(old)], "name": new_name}
        if doc["last_applied"] == old:
            doc["last_applied"] = new_name
        _write(Path(root), doc, damaged=damaged)


def set_last_applied(root: Path, name: str | None) -> None:
    """Remember ``name`` as the last applied preset (``None`` clears it).

    Raises ``PresetNotFoundError`` for an unknown name."""
    with _LOCK:
        doc, damaged = _read(Path(root))
        if name is not None and name not in {p["name"] for p in doc["presets"]}:
            raise PresetNotFoundError(name)
        doc["last_applied"] = name
        _write(Path(root), doc, damaged=damaged)


def _sub(info: dict[str, Any], key: str) -> dict[str, Any]:
    """``info[key]`` when it is an object, else an empty one."""
    v = info.get(key)
    return v if isinstance(v, dict) else {}


def _first(*candidates: Any) -> Any:
    """The first candidate that is not ``None`` (``None`` when all are)."""
    return next((c for c in candidates if c is not None), None)


def thermal_from_camera_info(info: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The writable node values in a ``camera_info()`` dict, and the writable names left out
    because the value is absent or ``None``.

    Spinnaker: ``nodes.IRFrameRate`` / ``nodes.NUCMode`` / ``nodes.CurrentCase``. Simulated:
    ``ir_frame_rate`` / ``nuc_mode``. Both: ``active_case.index``, ``nuc_mode``, ``ir_frame_rate``
    and ``object_parameters`` (its read-only ``EstimatedTransmission`` and
    ``UseWindowTemperature`` are not writable nodes and so never appear).
    """
    nodes = _sub(info, "nodes")
    params = _sub(info, "object_parameters")
    case = _sub(info, "active_case")
    found: dict[str, Any] = {name: params.get(name) for name in FLOAT_NODES}
    found["CurrentCase"] = _first(case.get("index"), nodes.get("CurrentCase"))
    found["NUCMode"] = _first(nodes.get("NUCMode"), info.get("nuc_mode"))
    found["IRFrameRate"] = _first(nodes.get("IRFrameRate"), info.get("ir_frame_rate"))
    values = {n: found[n] for n in WRITABLE_NODES if found.get(n) is not None}
    return values, [n for n in WRITABLE_NODES if n not in values]


def limits_from_camera_info(info: dict[str, Any]) -> tuple[dict[str, list[str]] | None, int | None]:
    """``(enum_options, n_cases)`` to validate a preset against: ``nodes.NumCases`` (Spinnaker) or
    the length of ``measurement_cases`` (simulated). ``(None, None)`` when the info has neither."""
    options = info.get("enum_options")
    cases = _sub(info, "nodes").get("NumCases")
    if not isinstance(cases, int) or isinstance(cases, bool):
        mc = info.get("measurement_cases")
        cases = len(mc) if isinstance(mc, list) else None
    if not isinstance(options, dict) or cases is None:
        return None, None
    return {k: list(v) for k, v in options.items()}, cases


__all__ = [
    "PRESETS_FILE",
    "PresetExistsError",
    "PresetNotFoundError",
    "delete_preset",
    "limits_from_camera_info",
    "load_presets",
    "normalize_name",
    "rename_preset",
    "save_preset",
    "set_last_applied",
    "thermal_from_camera_info",
    "validate_preset",
]
