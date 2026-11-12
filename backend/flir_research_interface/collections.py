"""Collections: per-user / per-project folders that group FLIR runs under an experiments root.

A run lives either at the top level of a root (``RunRef(None, name)``) or one level down inside a
collection folder (``RunRef(collection, name)``). This module holds the pure model: name rules,
run references, directory classification and the persisted "selected collection" file.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from lab_storage import fsutil as _fsutil

from .storage import _atomic_json

logger = logging.getLogger(__name__)

__all__ = [
    "SELECTION_FILE",
    "STORE_NAME",
    "NAME_RE",
    "RUN_LIKE_RE",
    "EntryKind",
    "RunRef",
    "RunQuery",
    "RootScan",
    "collection_name_error",
    "run_name_error",
    "classify_entry",
    "scan_root",
    "load_selection",
    "save_selection",
    "RENAMES_FILE",
    "load_renames",
    "record_rename",
]

SELECTION_FILE = ".collection.json"
STORE_NAME = "thermal.zarr"  # == recording.recorder.STORE_NAME (test-enforced; no recorder import)
NAME_RE = re.compile(r"^[a-z0-9_-]{1,40}$")
RUN_LIKE_RE = re.compile(r"^\d{8}_\d{6}(_|$)")

EntryKind = Literal["run", "collection", "unexpected", "skip"]


def collection_name_error(name: str) -> str | None:
    """None when ``name`` is a valid collection name, otherwise a user-facing reason."""
    if name.startswith("."):
        return "A collection name cannot start with a dot."
    if RUN_LIKE_RE.match(name):
        return "A collection name cannot look like a run folder (YYYYMMDD_HHMMSS...)."
    if not NAME_RE.fullmatch(name):
        return "Use 1-40 characters: lowercase letters, digits, '-' and '_'."
    return None


def run_name_error(name: str) -> str | None:
    """Reject names that could escape or alias a directory (same rule as ``_exp_dir``)."""
    if name in ("", ".", "..") or "/" in name or "\\" in name:
        return "Invalid run name."
    return None


@dataclass(frozen=True)
class RunRef:
    """A run's location: ``collection`` is None for the top level of a root."""

    collection: str | None
    name: str

    @property
    def key(self) -> str:
        return f"{self.collection}/{self.name}" if self.collection else self.name

    def rel(self) -> Path:
        return Path(self.collection) / self.name if self.collection else Path(self.name)

    @classmethod
    def from_dir(cls, run_dir: Path, roots: Sequence[Path]) -> RunRef:
        parent = run_dir.parent.resolve()
        if any(parent == Path(r).resolve() for r in roots):
            return cls(None, run_dir.name)
        return cls(run_dir.parent.name, run_dir.name)


@dataclass(frozen=True)
class RunQuery:
    """A request's run address: ``collection`` is None when the caller omitted it (legacy unique
    lookup), "" for the top level, or a collection name."""

    name: str
    collection: str | None


def classify_entry(path: Path) -> EntryKind:
    """What a directory entry directly under a root is."""
    name = path.name
    if not _fsutil.listable(name) or name.startswith(".") or not path.is_dir():
        return "skip"
    if (
        RUN_LIKE_RE.match(name)
        or (path / "metadata.json").exists()
        or (path / STORE_NAME).exists()
    ):
        return "run"
    if collection_name_error(name) is None:
        return "collection"
    return "unexpected"


@dataclass(frozen=True)
class RootScan:
    collections: tuple[str, ...]
    runs: tuple[str, ...]
    unexpected: tuple[str, ...]


def scan_root(root: Path) -> RootScan:
    """Classify every entry directly under ``root``; a missing root scans empty."""
    buckets: dict[str, list[str]] = {"collection": [], "run": [], "unexpected": []}
    if root.is_dir():
        for p in root.iterdir():
            kind = classify_entry(p)
            if kind != "skip":
                buckets[kind].append(p.name)
    return RootScan(
        collections=tuple(sorted(buckets["collection"])),
        runs=tuple(sorted(buckets["run"])),
        unexpected=tuple(sorted(buckets["unexpected"])),
    )


def load_selection(base: Path) -> str | None:
    """The persisted selection: a valid name, "" (Unsorted) or None (missing/malformed/invalid)."""
    try:
        data = json.loads((base / SELECTION_FILE).read_text())
    except (OSError, ValueError):
        return None
    sel = data.get("selected") if isinstance(data, dict) else None
    if not isinstance(sel, str):
        return None
    if sel == "" or collection_name_error(sel) is None:
        return sel
    return None


def save_selection(base: Path, selected: str | None) -> None:
    """Atomically persist the selection; ValueError for an invalid collection name."""
    if selected:
        err = collection_name_error(selected)
        if err:
            raise ValueError(err)
    base.mkdir(parents=True, exist_ok=True)
    _atomic_json(base / SELECTION_FILE, {"selected": selected})


RENAMES_FILE = ".collection-renames.json"


def load_renames(base: Path) -> list[dict[str, object]]:
    """Every collection rename, oldest first (``[]`` when missing or unreadable). Browsers use it to
    move their per-run settings from ``<old>/<run>`` to ``<new>/<run>``."""
    try:
        data = json.loads((base / RENAMES_FILE).read_text())
    except (OSError, ValueError):
        return []
    items = data.get("renames") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return [
        r for r in items
        if isinstance(r, dict) and isinstance(r.get("from"), str) and isinstance(r.get("to"), str)
    ]


def record_rename(base: Path, old: str, new: str, at: float) -> None:
    items = load_renames(base)
    items.append({"from": old, "to": new, "at": at})
    _atomic_json(base / RENAMES_FILE, {"renames": items})
