"""Auto-offload: finished runs move from this Mac to the registered SSD on their own.

A run is always recorded on the Mac, so an SSD that drops off mid-recording (the hub has done
it) can never touch the recording. When the run is finalized it joins a queue in
``<local root>/.auto-offload.json``; a sweep moves it with ``storage.move_experiment`` (hashed
while copying, re-read from the SSD, then the Mac copy deleted) once the SSD is connected, no
recording/arm/closed-loop session is active, and the run's post-stop exports are done. A failed
move leaves the Mac copy intact and is retried with back-off, then flagged after
``MAX_ATTEMPTS``. The queue survives restarts.

    {"enabled": true,
     "pending": [{"collection": "rf-heating", "name": "20261112_150000_run", "queued": 1.7e9,
                  "attempts": 0, "last_try": null, "error": null}]}
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from .storage import _atomic_json

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_ATTEMPTS",
    "OFFLOAD_FILE",
    "RETRY_S",
    "decide",
    "finish",
    "load_offload",
    "queue_run",
    "record_failure",
    "retry_all",
    "set_enabled",
]

OFFLOAD_FILE = ".auto-offload.json"
MAX_ATTEMPTS = 5
RETRY_S = 120.0  # wait attempts x RETRY_S after a failure before trying again
_LOCK = threading.Lock()


def _read(base: Path) -> tuple[dict[str, Any], bool]:
    """The queue doc and whether the file may be overwritten (missing or readable)."""
    empty: dict[str, Any] = {"enabled": True, "pending": []}
    try:
        data = json.loads((base / OFFLOAD_FILE).read_text())
    except FileNotFoundError:
        return empty, True
    except (OSError, ValueError) as exc:
        logger.warning("offload queue unreadable (%s); left untouched", exc)
        return empty, False
    if not isinstance(data, dict) or not isinstance(data.get("pending"), list):
        logger.warning("offload queue has an unexpected shape; left untouched")
        return empty, False
    pending = [
        e for e in data["pending"]
        if isinstance(e, dict) and isinstance(e.get("collection"), str)
        and isinstance(e.get("name"), str)
    ]
    return {"enabled": data.get("enabled", True) is not False, "pending": pending}, True


def load_offload(base: Path) -> dict[str, Any]:
    return _read(base)[0]


def _update(base: Path, fn: Any) -> None:
    with _LOCK:
        doc, ok = _read(base)
        if not ok:
            return
        fn(doc)
        base.mkdir(parents=True, exist_ok=True)
        _atomic_json(base / OFFLOAD_FILE, doc)


def _same(e: dict[str, Any], collection: str, name: str) -> bool:
    return bool(e["collection"] == collection and e["name"] == name)


def set_enabled(base: Path, on: bool) -> None:
    _update(base, lambda d: d.__setitem__("enabled", bool(on)))


def queue_run(base: Path, collection: str, name: str, *, now: float) -> None:
    def fn(d: dict[str, Any]) -> None:
        if not any(_same(e, collection, name) for e in d["pending"]):
            d["pending"].append({"collection": collection, "name": name, "queued": now,
                                 "attempts": 0, "last_try": None, "error": None})
    _update(base, fn)


def finish(base: Path, collection: str, name: str) -> None:
    def fn(d: dict[str, Any]) -> None:
        d["pending"] = [e for e in d["pending"] if not _same(e, collection, name)]
    _update(base, fn)


def record_failure(base: Path, collection: str, name: str, error: str, *, now: float,
                   permanent: bool = False) -> None:
    def fn(d: dict[str, Any]) -> None:
        for e in d["pending"]:
            if _same(e, collection, name):
                e["attempts"] = MAX_ATTEMPTS if permanent else int(e.get("attempts", 0)) + 1
                e["last_try"], e["error"] = now, error
    _update(base, fn)


def retry_all(base: Path) -> None:
    def fn(d: dict[str, Any]) -> None:
        for e in d["pending"]:
            e["attempts"], e["last_try"], e["error"] = 0, None, None
    _update(base, fn)


def decide(
    entry: dict[str, Any], *, now: float, drive: bool, idle: bool, src_exists: bool,
    dst_exists: bool, run_busy: bool,
) -> str:
    """What to do with one queued run right now: ``move``, ``done`` (already on the SSD),
    ``gone`` (no longer on the Mac, not on the SSD), ``clash`` (a different run of that name is
    on the SSD), ``stuck`` (gave up after repeated failures) or ``wait:<reason>``."""
    if not src_exists:
        return "done" if dst_exists else "gone"
    attempts = int(entry.get("attempts") or 0)
    if attempts >= MAX_ATTEMPTS:
        return "stuck"
    if not drive:
        return "wait:SSD not connected"
    if dst_exists:
        return "clash"
    if not idle:
        return "wait:a recording is active"
    if run_busy:
        return "wait:finishing exports"
    last = entry.get("last_try")
    if attempts and last is not None and now - float(last) < attempts * RETRY_S:
        return "wait:retrying soon"
    return "move"
