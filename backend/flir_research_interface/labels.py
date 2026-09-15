"""Per-run organization metadata (star + free-form tags) stored in a ``labels.json`` sidecar.

The sidecar lives inside the run folder so stars/tags travel with the data across machines and the
external drive. All access is tolerant (a missing or corrupt file reads as the default) and writes
are atomic (temp + ``os.replace``) so a crash never corrupts it.
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


def read_labels(run_dir: Path | str) -> dict[str, Any]:
    """``{"starred": bool, "tags": [str]}`` — the default on a missing/blank/corrupt file."""
    default: dict[str, Any] = {"starred": False, "tags": []}
    path = Path(run_dir) / LABELS_FILE
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return default
    if not isinstance(data, dict):
        return default
    return {
        "starred": bool(data.get("starred", False)),
        "tags": normalize_tags(data.get("tags") or []),
    }


def write_labels(run_dir: Path | str, *, starred: bool, tags: Iterable[str]) -> dict[str, Any]:
    """Normalize and atomically write the sidecar; return the stored dict."""
    run_dir = Path(run_dir)
    stored: dict[str, Any] = {"starred": bool(starred), "tags": normalize_tags(tags)}
    run_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=run_dir, prefix=".labels-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(stored, f)
        os.replace(tmp, run_dir / LABELS_FILE)
    finally:
        Path(tmp).unlink(missing_ok=True)  # no-op after a successful replace
    return stored


__all__ = ["LABELS_FILE", "normalize_tags", "read_labels", "write_labels"]
