"""Small concurrency helpers for the operator."""

from __future__ import annotations

import asyncio


class KeyedLocks:
    """Lazily-created ``asyncio.Lock`` per key.

    Used to serialise work that writes the same experiment's files — the post-stop thermal-video
    render and an on-demand derived regenerate must not run at once on the same run, or they would
    both write ``exports/thermal_preview_rois.mp4`` (and its ``.part.mp4``) and corrupt it. Locks
    for different keys are independent, so unrelated runs still render in parallel.
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def get(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock


__all__ = ["KeyedLocks"]
