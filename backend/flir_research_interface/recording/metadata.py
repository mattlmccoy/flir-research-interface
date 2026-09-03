"""Post-hoc edits to an experiment's ``metadata.json`` (Milestone 8).

Only the ``experiment`` block (operator-entered fields) is editable; camera, software and
conversion blocks are facts captured at record time and stay untouched. Every edit appends an
entry to ``edits`` so the file remains auditable. Writes are atomic.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESERVED_KEYS = frozenset({"name"})


def patch_experiment_metadata(exp_dir: Path, changes: dict[str, Any]) -> dict[str, Any]:
    """Merge ``changes`` into ``metadata.json[experiment]``; ``None`` deletes a key.

    Raises ``FileNotFoundError`` when the directory has no metadata and ``ValueError`` for a
    reserved key. Returns the updated metadata document.
    """
    path = Path(exp_dir) / "metadata.json"
    if not path.is_file():
        raise FileNotFoundError(f"no metadata.json in {exp_dir}")
    bad = RESERVED_KEYS & set(changes)
    if bad:
        raise ValueError(f"{sorted(bad)} cannot be edited (reserved)")
    meta: dict[str, Any] = json.loads(path.read_text())
    exp = dict(meta.get("experiment") or {})
    for k, v in changes.items():
        if v is None:
            exp.pop(k, None)
        else:
            exp[k] = v
    meta["experiment"] = exp
    edits = list(meta.get("edits") or [])
    edits.append(
        {
            "t_utc": datetime.now(timezone.utc).isoformat(),
            "keys": sorted(changes),
            "block": "experiment",
        }
    )
    meta["edits"] = edits
    _atomic_write(path, meta)
    return meta


def _atomic_write(path: Path, meta: dict[str, Any]) -> None:
    """Write ``meta`` to ``path`` atomically (write a sibling temp file, then rename)."""
    fd, tmp = tempfile.mkstemp(prefix=".metadata.", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(meta, indent=2, default=str))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def set_experiment_rois(exp_dir: Path, rois: list[dict[str, Any]]) -> dict[str, Any]:
    """Replace ``metadata.json['rois']`` with ``rois`` (already validated by ``parse_rois``).

    Lets ROIs added or edited during playback be persisted so the derived exports (roi_series,
    roi_plot, peak frames, thermal videos) can be regenerated to match them. Records the edit and
    returns the updated metadata document. Raises ``FileNotFoundError`` when there is no metadata.
    """
    path = Path(exp_dir) / "metadata.json"
    if not path.is_file():
        raise FileNotFoundError(f"no metadata.json in {exp_dir}")
    meta: dict[str, Any] = json.loads(path.read_text())
    meta["rois"] = rois
    edits = list(meta.get("edits") or [])
    edits.append(
        {
            "t_utc": datetime.now(timezone.utc).isoformat(),
            "keys": ["rois"],
            "block": "rois",
        }
    )
    meta["edits"] = edits
    _atomic_write(path, meta)
    return meta


__all__ = ["RESERVED_KEYS", "patch_experiment_metadata", "set_experiment_rois"]
