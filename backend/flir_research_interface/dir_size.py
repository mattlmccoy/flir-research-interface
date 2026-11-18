"""Run folder sizes for the experiments list, measured once and reused until a folder changes.

Summing a run means stat-ing every file (a 30k-frame run's zarr store is ~800 chunk files; 102 runs
on the exFAT SSD are 78k files: 2.5 s idle, 18-28 s while the camera streams). Each folder's
listing and file bytes are remembered with its ``mtime_ns``; a later call only ``stat``s the
folders and re-lists one whose mtime moved (a file added, removed or replaced: zarr chunks and
exports are written by rename). A file grown in place without touching its folder (only while a
run records) is not seen; callers pass ``fresh=True`` for that run.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

__all__ = ["DirSizeCache"]


def _file_bytes(path: str) -> int:
    try:
        return os.stat(path, follow_symlinks=False).st_size
    except OSError:
        return 0


@dataclass(frozen=True)
class _Folder:
    mtime_ns: int
    subdirs: tuple[str, ...]
    file_bytes: int


def _list(path: str, mtime_ns: int) -> _Folder:
    subdirs: list[str] = []
    total = 0
    try:
        entries = list(os.scandir(path))
    except OSError:
        return _Folder(mtime_ns, (), 0)
    for e in entries:
        try:
            if e.is_dir(follow_symlinks=False):
                subdirs.append(e.path)
                continue
        except OSError:
            continue
        total += _file_bytes(e.path)
    return _Folder(mtime_ns, tuple(subdirs), total)


class DirSizeCache:
    """``size(run_dir)`` in bytes; a missing folder is 0."""

    def __init__(self) -> None:
        self._folders: dict[str, _Folder] = {}
        self._lock = threading.Lock()

    def size(self, path: Path, *, fresh: bool = False) -> int:
        total = 0
        stack = [str(path)]
        while stack:
            d = stack.pop()
            try:
                mtime = os.stat(d).st_mtime_ns
            except OSError:
                with self._lock:
                    self._folders.pop(d, None)
                continue
            with self._lock:
                hit = self._folders.get(d)
            if fresh or hit is None or hit.mtime_ns != mtime:
                hit = _list(d, mtime)
                with self._lock:
                    self._folders[d] = hit
            total += hit.file_bytes
            stack.extend(hit.subdirs)
        return total
