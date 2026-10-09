"""Per-run organization metadata (star, free-form tags, display title, notes) in a ``labels.json``
sidecar.

The sidecar lives inside the run folder so stars/tags travel with the data across machines and the
external drive. All access is tolerant (a missing or corrupt file reads as the default) and writes
are atomic (temp + ``os.replace``) so a crash never corrupts it. The title is a display name only:
the run folder (its identity everywhere else) is never renamed. Title/notes keys are present only
when set, and a write that does not pass them keeps the stored ones.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

LABELS_FILE = "labels.json"
_MAX_TAG_LEN = 40
_MAX_TITLE_LEN = 120
_MAX_NOTES_LEN = 10_000
_KEEP: Any = object()  # sentinel: leave the stored title/notes as they are


def normalize_tags(raw: Iterable[str]) -> list[str]:
    """Trim, collapse internal whitespace, drop empties, cap length, de-duplicate
    case-insensitively (keeping the first-seen casing), preserving order. The one valid-tag rule."""
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        tag = " ".join(str(item).split())[:_MAX_TAG_LEN].strip()
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return out


def normalize_title(raw: str | None) -> str | None:
    """One line, whitespace collapsed, capped; blank means no title."""
    t = " ".join(str(raw or "").split())[:_MAX_TITLE_LEN].strip()
    return t or None


def normalize_notes(raw: str | None) -> str | None:
    """Free text (line breaks kept), ends trimmed, capped; blank means no notes."""
    n = str(raw or "").strip()[:_MAX_NOTES_LEN].strip()
    return n or None


def read_labels(run_dir: Path | str) -> dict[str, Any]:
    """``{"starred": bool, "tags": [str]}`` plus ``title`` / ``notes`` when set — the default on a
    missing/blank/corrupt file."""
    default: dict[str, Any] = {"starred": False, "tags": []}
    path = Path(run_dir) / LABELS_FILE
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return default
    if not isinstance(data, dict):
        return default
    out: dict[str, Any] = {
        "starred": bool(data.get("starred", False)),
        "tags": normalize_tags(data.get("tags") or []),
    }
    for key, norm in (("title", normalize_title), ("notes", normalize_notes)):
        val = norm(data.get(key)) if isinstance(data.get(key), str) else None
        if val:
            out[key] = val
    return out


def write_labels(
    run_dir: Path | str, *, starred: bool, tags: Iterable[str],
    title: str | None = _KEEP, notes: str | None = _KEEP,
) -> dict[str, Any]:
    """Normalize and atomically write the sidecar; return the stored dict. ``title`` / ``notes``
    left out keep their stored values; ``""`` or ``None`` clears them."""
    run_dir = Path(run_dir)
    old = read_labels(run_dir)
    stored: dict[str, Any] = {"starred": bool(starred), "tags": normalize_tags(tags)}
    t = old.get("title") if title is _KEEP else normalize_title(title)
    n = old.get("notes") if notes is _KEEP else normalize_notes(notes)
    if t:
        stored["title"] = t
    if n:
        stored["notes"] = n
    run_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=run_dir, prefix=".labels-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(stored, f)
        os.replace(tmp, run_dir / LABELS_FILE)
    finally:
        Path(tmp).unlink(missing_ok=True)  # no-op after a successful replace
    return stored


__all__ = [
    "LABELS_FILE", "normalize_notes", "normalize_tags", "normalize_title", "read_labels",
    "write_labels",
]
