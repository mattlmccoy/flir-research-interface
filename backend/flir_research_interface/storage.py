"""External-drive offload storage.

Detects user-selectable external drives across macOS/Windows/Linux, remembers one registered
drive, and moves a run to it copy → verify → delete-source so science data is never lost. Recording
always stays on local disk; this module only offloads finished runs. See the design spec at
``docs/superpowers/specs/2026-09-03-external-drive-storage-design.md``.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

#: Folder created on a registered drive to hold offloaded runs.
DRIVE_SUBDIR = "FLIR-recordings"


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


__all__ = ["DRIVE_SUBDIR", "selectable_drives"]
