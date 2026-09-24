"""External-drive offload storage — FLIR's adapter over the shared ``lab-storage`` library.

Detects user-selectable external drives across macOS/Windows/Linux, remembers one registered
drive, and moves a finished run to it and back. The move itself (copy with a streamed SHA-256 →
device flush → cache-bypassing re-read → atomic rename → source deleted last), drive detection,
the shared drive marker and exFAT quirks live in ``lab_storage``
(https://github.com/mattlmccoy/lab-storage); this module keeps FLIR's config file and the API the
routes use. Recording always stays on local disk. Design history:
``docs/superpowers/specs/2026-09-03-external-drive-storage-design.md``.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import lab_storage
from lab_storage import drives as _drives
from lab_storage import fsutil as _fsutil

logger = logging.getLogger(__name__)

#: Folder created on a registered drive to hold offloaded runs.
DRIVE_SUBDIR = "FLIR-recordings"
#: Sidecar in the local root that remembers the registered drive (git-ignored).
CONFIG_NAME = ".storage.json"
#: This tool's name in the shared drive marker (``<mount>/.lab-storage.json``).
TOOL = "flir"
#: Small integrity-critical files that ``verify_copy`` always hash-compares.
CRITICAL_FILES = frozenset({"metadata.json", "manifest.json"})
#: Files FLIR rewrites inside a run after recording (stars/tags, exports); a conflict that differs
#: only in these is reported as sidecar-only.
MUTABLE_PATHS = ("labels.json", "exports/*")


class MoveConflictError(RuntimeError):
    """The destination already holds this run with different content; both copies were kept."""


@dataclass(frozen=True)
class _Part:
    """The subset of ``psutil`` sdiskpart this module needs (also lets tests inject samples)."""

    device: str
    mountpoint: str
    fstype: str
    opts: str


def _alloc_unit(path: str | Path) -> int:
    return int(_drives.alloc_unit(str(path)))


def selectable_drives(
    platform: str,
    parts: list[_Part] | None = None,
    usage: Callable[[str], tuple[int, int]] | None = None,
) -> list[dict[str, Any]]:
    """User-selectable external drives for offload (writable, not system/hidden volumes).

    ``platform`` is ``sys.platform``. ``parts``/``usage`` default to the live system; tests pass
    captured samples (``usage`` returns ``(total, free)``).
    """
    kw: dict[str, Any] = {}
    if parts is not None:
        kw["parts"] = [_drives.Partition(p.device, p.mountpoint, p.fstype, p.opts) for p in parts]
    if usage is not None:
        def _u(m: str) -> tuple[int, int, int]:
            total, free = usage(m)
            return total, total - free, free

        kw["usage"] = _u
        kw["alloc"] = lambda m: 4096  # injected samples have no real volume to statvfs
    return [
        {
            "label": d.label,
            "mount": d.mount,
            "fstype": d.fs_type,
            "total_bytes": d.total_bytes,
            "free_bytes": d.free_bytes,
        }
        for d in lab_storage.list_external_drives(platform, **kw)
    ]


def _external_mounts() -> list[str]:
    return [d.mount for d in lab_storage.list_external_drives()]


# -- registered-drive config -------------------------------------------------------------------


def load_storage_config(local_root: Path | str) -> dict[str, Any]:
    """Read the config sidecar; a missing or malformed file means no drive is registered."""
    path = Path(local_root) / CONFIG_NAME
    try:
        cfg = json.loads(path.read_text())
        if isinstance(cfg, dict) and isinstance(cfg.get("drive"), dict | type(None)):
            return {"drive": cfg["drive"]}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return {"drive": None}


def save_storage_config(local_root: Path | str, cfg: dict[str, Any]) -> None:
    """Atomically write the storage config (temp file + rename)."""
    path = Path(local_root) / CONFIG_NAME
    fd, tmp = tempfile.mkstemp(prefix=".storage.", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(cfg, indent=2))
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def _ensure_marker(mount: Path) -> str | None:
    """Add FLIR to the drive's shared marker (created if absent, existing folders untouched).
    Best effort: a read-only or corrupt marker leaves the drive registered by path only."""
    try:
        m = lab_storage.ensure_marker(mount, TOOL, DRIVE_SUBDIR, label=mount.name)
        return str(m["drive_id"])
    except (lab_storage.MarkerError, OSError) as exc:
        logger.warning("drive marker not written on %s: %s", mount, exc)
        return None


def register_drive(local_root: Path | str, mount: str) -> dict[str, Any]:
    """Register ``mount`` as the offload drive: create ``<mount>/FLIR-recordings/``, write-probe it,
    record FLIR in the drive marker, and persist. Raises ``ValueError`` if the drive is missing or
    not writable."""
    mount_path = Path(mount)
    if not mount_path.is_dir():
        raise ValueError(f"{mount} is not a mounted folder")
    root = mount_path / DRIVE_SUBDIR
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".fri-write-probe"
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:
        raise ValueError(f"{mount} is not writable: {exc}") from exc
    drive: dict[str, Any] = {"mount": str(mount_path), "root": str(root)}
    drive_id = _ensure_marker(mount_path)
    if drive_id:
        drive["drive_id"] = drive_id
    cfg = {"drive": drive}
    save_storage_config(local_root, cfg)
    with contextlib.suppress(FileNotFoundError):  # a new drive: rebuilt on the next listing
        (Path(local_root) / INDEX_NAME).unlink()
    return cfg


def adopt_marker(local_root: Path | str) -> None:
    """Give a pre-lab-storage registration (``{mount, root}`` only) a drive id, if its drive is
    connected. Call from write operations only (a scan never writes to the drive)."""
    cfg = load_storage_config(local_root)
    drive = cfg["drive"]
    if not drive or drive.get("drive_id") or not Path(drive["root"]).is_dir():
        return
    drive_id = _ensure_marker(Path(drive["mount"]))
    if drive_id:
        save_storage_config(local_root, {"drive": {**drive, "drive_id": drive_id}})


def connected_drive(local_root: Path | str) -> dict[str, Any] | None:
    """The registered drive's ``{mount, root}`` if it is connected, else ``None``. The saved mount
    path is tried first; if it is gone (volume renamed, other OS), external drives are searched for
    the marker with the saved drive id."""
    drive = load_storage_config(local_root)["drive"]
    if not drive:
        return None
    drive_id = drive.get("drive_id")
    if Path(drive["root"]).is_dir():
        marker = _read_marker(drive["mount"])
        if not drive_id or marker is None or marker.get("drive_id") == drive_id:
            return {"mount": drive["mount"], "root": drive["root"]}
    if not drive_id:
        return None
    for mount in _external_mounts():
        marker = _read_marker(mount)
        if marker and marker.get("drive_id") == drive_id:
            folder = marker.get("tools", {}).get(TOOL, {}).get("folder", DRIVE_SUBDIR)
            root = Path(mount) / folder
            if root.is_dir():
                return {"mount": mount, "root": str(root)}
    return None


def _read_marker(mount: str) -> dict[str, Any] | None:
    try:
        m = lab_storage.read_marker(mount)
        return dict(m) if m is not None else None
    except (lab_storage.MarkerError, OSError):
        return None


def forget_drive(local_root: Path | str) -> dict[str, Any]:
    """Forget the registered drive (leaves its files and marker in place) and its offline index."""
    cfg = {"drive": None}
    save_storage_config(local_root, cfg)
    with contextlib.suppress(FileNotFoundError):
        (Path(local_root) / INDEX_NAME).unlink()
    return cfg


# -- offline index: remember what is on the drive so an unplugged drive's runs stay listed -------

#: Local snapshot of the registered drive's run cards, refreshed whenever the drive is listed.
INDEX_NAME = ".drive-index.json"


def remember_drive_runs(local_root: Path | str, items: list[dict[str, Any]], label: str) -> None:
    """Snapshot the connected drive's run summaries (rewritten only when they change)."""
    runs = sorted(
        ({k: v for k, v in it.items() if k not in ("root", "library")} for it in items),
        key=lambda r: str(r.get("name", "")),
    )
    path = Path(local_root) / INDEX_NAME
    old = _read_index(path)
    if old.get("label") == label and old.get("runs") == runs:
        return
    now = datetime.now(UTC).isoformat(timespec="seconds")
    _atomic_json(path, {"label": label, "last_seen_utc": now, "runs": runs})


def offline_runs(local_root: Path | str) -> list[dict[str, Any]]:
    """The last-seen runs of the registered drive, marked ``library: "offline"`` so they can never
    be mistaken for runs that are actually readable right now."""
    idx = _read_index(Path(local_root) / INDEX_NAME)
    label, seen = idx.get("label", "drive"), idx.get("last_seen_utc")
    return [
        {**r, "library": "offline", "offline": True, "drive_label": label, "last_seen_utc": seen}
        for r in idx.get("runs", [])
        if isinstance(r, dict) and r.get("name")
    ]


def _read_index(path: Path) -> dict[str, Any]:
    try:
        idx = json.loads(path.read_text())
        return idx if isinstance(idx, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    fd, tmp = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, default=str)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


# -- verification helper (kept for callers/tests; moves verify inside lab-storage) ---------------


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_os_junk(name: str) -> bool:
    return bool(_fsutil.is_junk(name))


def verify_copy(src: Path | str, dst: Path | str, *, full: bool = False) -> str | None:
    """Confirm ``dst`` is a faithful copy of ``src``. Returns ``None`` when good, else a reason.
    Sizes always; SHA-256 for metadata/manifest, or for every file with ``full=True``."""
    src, dst = Path(src), Path(dst)
    for sp in src.rglob("*"):
        if not sp.is_file() or _is_os_junk(sp.name):
            continue
        rel = sp.relative_to(src)
        dp = dst / rel
        if not dp.is_file():
            return f"missing in copy: {rel}"
        if sp.stat().st_size != dp.stat().st_size:
            return f"size mismatch: {rel}"
        if (full or sp.name in CRITICAL_FILES) and _sha256(sp) != _sha256(dp):
            return f"checksum mismatch: {rel}"
    return None


# -- move ----------------------------------------------------------------------------------------


def move_experiment(
    src_run: Path | str,
    dst_root: Path | str,
    *,
    on_progress: Callable[[int, int], None] | None = None,
    full_verify: bool = False,  # noqa: ARG001 - lab-storage always re-reads every file
) -> Path:
    """Move one run folder into ``dst_root`` via ``lab_storage.move_dataset``.

    Every file is hashed while copying and re-read from the device before the source is deleted
    (so ``full_verify`` is always on). Raises ``ValueError`` when the move was refused before
    starting (e.g. not enough space, counted in allocation units), ``MoveConflictError`` when a
    different copy already sits at the destination (both kept), and ``RuntimeError`` for other
    failures; the source is intact in every error case. Returns the destination path.
    """
    src_run, dst_root = Path(src_run), Path(dst_root)
    dst_root.mkdir(parents=True, exist_ok=True)
    name = src_run.name
    dst = dst_root / name
    try:
        unit = _alloc_unit(dst_root)
    except OSError as exc:
        raise ValueError(f"cannot read the destination's allocation unit: {exc}") from exc
    try:
        res = lab_storage.move_dataset(
            src_run, dst, key=name, on_progress=on_progress, mutable_paths=MUTABLE_PATHS,
            alloc_unit=unit, free_bytes=shutil.disk_usage(dst_root).free,
        )
    except lab_storage.Refused as exc:
        raise ValueError(str(exc)) from exc
    except lab_storage.ConflictError as exc:
        raise MoveConflictError(f"{exc}; both copies were kept") from exc
    except lab_storage.VerifyError as exc:
        raise RuntimeError(f"copy verification failed: {exc}") from exc
    except lab_storage.SourceNotRemoved as exc:
        try:  # copy verified and in place; retry removing the original once
            res = lab_storage.finish_source_removal(exc.remaining, dst, key=name)
        except Exception as again:  # noqa: BLE001 - report both; the copy is safe
            raise RuntimeError(
                f"{name} was copied and verified, but the original could not be removed "
                f"({again}); it is at {exc.remaining}"
            ) from again
    except (lab_storage.SourceChanged, lab_storage.NotDurable) as exc:
        raise RuntimeError(str(exc)) from exc
    # lab-storage renames the source before deleting it, so an exFAT "._<name>" AppleDouble sidecar
    # next to the original folder can be left behind; it is OS junk, never data.
    with contextlib.suppress(FileNotFoundError):
        (src_run.parent / f"._{name}").unlink()
    if on_progress is not None:
        on_progress(res.size_bytes, res.size_bytes)
    return dst


__all__ = [
    "CONFIG_NAME",
    "CRITICAL_FILES",
    "DRIVE_SUBDIR",
    "MoveConflictError",
    "adopt_marker",
    "connected_drive",
    "forget_drive",
    "offline_runs",
    "remember_drive_runs",
    "load_storage_config",
    "move_experiment",
    "register_drive",
    "save_storage_config",
    "selectable_drives",
    "verify_copy",
]
