"""External-drive offload storage.

Detects user-selectable external drives across macOS/Windows/Linux, remembers one registered
drive, and moves a run to it copy → verify → delete-source so science data is never lost. Recording
always stays on local disk; this module only offloads finished runs. See the design spec at
``docs/superpowers/specs/2026-09-03-external-drive-storage-design.md``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

#: Folder created on a registered drive to hold offloaded runs.
DRIVE_SUBDIR = "FLIR-recordings"
#: Sidecar in the local root that remembers the registered drive (git-ignored).
CONFIG_NAME = ".storage.json"
#: Small integrity-critical files that are hash-verified after a copy (the rest are size-verified).
CRITICAL_FILES = frozenset({"metadata.json", "manifest.json"})


@dataclass(frozen=True)
class _Part:
    """The subset of ``psutil`` sdiskpart this module needs (also lets tests inject samples)."""

    device: str
    mountpoint: str
    fstype: str
    opts: str


def _live_parts() -> list[_Part]:
    return [
        _Part(p.device, p.mountpoint, p.fstype, p.opts)
        for p in psutil.disk_partitions(all=False)
    ]


def _default_usage(mount: str) -> tuple[int, int]:
    du = shutil.disk_usage(mount)
    return du.total, du.free


def selectable_drives(
    platform: str,
    parts: list[_Part] | None = None,
    usage: Callable[[str], tuple[int, int]] | None = None,
) -> list[dict[str, Any]]:
    """User-selectable external drives for offload, filtered from every mounted volume.

    ``platform`` is ``sys.platform`` ("darwin"/"linux"/"win32"). ``parts``/``usage`` default to the
    live system; tests pass captured samples. Read-only mounts (system volumes, mounted DMGs,
    read-only NTFS) are excluded — an offload target must be writable.
    """
    parts = _live_parts() if parts is None else parts
    usage = usage or _default_usage
    out: list[dict[str, Any]] = []
    for p in parts:
        if not _is_external(platform, p):
            continue
        try:
            total, free = usage(p.mountpoint)
        except OSError:
            continue  # a volume that vanished between listing and stat
        out.append(
            {
                "label": Path(p.mountpoint).name or p.device,
                "mount": p.mountpoint,
                "fstype": p.fstype,
                "total_bytes": total,
                "free_bytes": free,
            }
        )
    return out


def _is_external(platform: str, p: _Part) -> bool:
    opts = p.opts.split(",")
    if "ro" in opts:
        return False  # read-only mounts are never offload targets
    if platform == "darwin":
        return p.mountpoint.startswith("/Volumes/") and Path(p.mountpoint).name != "Macintosh HD"
    if platform == "linux":
        prefixes = ("/media/", "/run/media/", "/mnt/")
        return any(p.mountpoint.startswith(pre) for pre in prefixes)
    if platform.startswith("win"):
        # NOTE: verify on a real Windows box before shipping (see the spec's verification plan).
        drive = p.mountpoint.rstrip("\\/").upper()
        return ("removable" in opts) or (drive not in ("", "C:") and p.fstype != "")
    return False


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
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def register_drive(local_root: Path | str, mount: str) -> dict[str, Any]:
    """Register ``mount`` as the offload drive: create ``<mount>/FLIR-recordings/``, write-probe it,
    and persist. Raises ``ValueError`` if the drive is missing or not writable."""
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
    cfg = {"drive": {"mount": str(mount_path), "root": str(root)}}
    save_storage_config(local_root, cfg)
    return cfg


def forget_drive(local_root: Path | str) -> dict[str, Any]:
    """Forget the registered drive (leaves its files in place)."""
    cfg = {"drive": None}
    save_storage_config(local_root, cfg)
    return cfg


# -- move: copy → verify → delete source -------------------------------------------------------


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_copy(src: Path | str, dst: Path | str) -> str | None:
    """Confirm ``dst`` is a faithful copy of ``src``. Returns ``None`` when good, else a reason.

    Every file under ``src`` must exist in ``dst`` with the same size; the integrity-critical small
    files (metadata/manifest) are additionally SHA-256 compared to catch same-size corruption.
    """
    src, dst = Path(src), Path(dst)
    for sp in src.rglob("*"):
        if not sp.is_file():
            continue
        rel = sp.relative_to(src)
        dp = dst / rel
        if not dp.is_file():
            return f"missing in copy: {rel}"
        if sp.stat().st_size != dp.stat().st_size:
            return f"size mismatch: {rel}"
        if sp.name in CRITICAL_FILES and _sha256(sp) != _sha256(dp):
            return f"checksum mismatch: {rel}"
    return None


__all__ = [
    "CONFIG_NAME",
    "CRITICAL_FILES",
    "DRIVE_SUBDIR",
    "forget_drive",
    "load_storage_config",
    "register_drive",
    "save_storage_config",
    "selectable_drives",
    "verify_copy",
]
