"""Visible↔IR alignment (planar homography) stored on the operator.

The browser fits the homography from point pairs; the operator only validates and keeps it,
so every browser shares one alignment and each recording's ``metadata.json`` carries the
alignment in force at record time (``visible_alignment``).
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FILE_NAME = "visible_alignment.json"


def calibration_dir(experiments_root: Path) -> Path:
    return Path(experiments_root).parent / "calibration"


def _is_pt(v: Any) -> bool:
    return (
        isinstance(v, list)
        and len(v) == 2
        and all(isinstance(x, int | float) and not isinstance(x, bool) for x in v)
    )


def validate_alignment(doc: Any) -> dict[str, Any]:
    """Return a clean copy or raise ``ValueError``. ``H`` may be null (pairs only, unsolved)."""
    if not isinstance(doc, dict):
        raise ValueError("alignment must be an object")
    h = doc.get("H")
    if h is not None:
        ok = (
            isinstance(h, list)
            and len(h) == 3
            and all(
                isinstance(r, list)
                and len(r) == 3
                and all(isinstance(x, int | float) and not isinstance(x, bool) for x in r)
                for r in h
            )
        )
        if not ok:
            raise ValueError("H must be a 3x3 matrix of numbers or null")
        h = [[float(x) for x in r] for r in h]
    pairs_in = doc.get("pairs", [])
    if not isinstance(pairs_in, list):
        raise ValueError("pairs must be a list")
    pairs = []
    for p in pairs_in:
        if not isinstance(p, dict) or not _is_pt(p.get("ir")) or not _is_pt(p.get("visible")):
            raise ValueError("each pair needs ir [x, y] and visible [x, y]")
        pairs.append(
            {"ir": [float(v) for v in p["ir"]], "visible": [float(v) for v in p["visible"]]}
        )
    rms = doc.get("rmsPx")
    if rms is not None and (isinstance(rms, bool) or not isinstance(rms, int | float)):
        raise ValueError("rmsPx must be a number or null")
    note = doc.get("note", "")
    if not isinstance(note, str):
        raise ValueError("note must be a string")
    return {"pairs": pairs, "H": h, "rmsPx": rms, "note": note[:120]}


def load_alignment(experiments_root: Path) -> dict[str, Any] | None:
    path = calibration_dir(experiments_root) / FILE_NAME
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        return None


def save_alignment(experiments_root: Path, doc: Any) -> dict[str, Any]:
    clean = validate_alignment(doc)
    clean["saved_utc"] = datetime.now(timezone.utc).isoformat()
    d = calibration_dir(experiments_root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / FILE_NAME
    fd, tmp = tempfile.mkstemp(prefix=".align.", suffix=".json", dir=d)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(clean, indent=2))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return clean


__all__ = ["FILE_NAME", "calibration_dir", "load_alignment", "save_alignment", "validate_alignment"]
