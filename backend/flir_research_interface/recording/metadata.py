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
    return meta


__all__ = ["RESERVED_KEYS", "patch_experiment_metadata"]
