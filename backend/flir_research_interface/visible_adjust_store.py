"""Where a run's visible-video adjustment lives, and which one wins.

Three sources, in precedence order:

1. ``visible_adjust.json`` in the run folder: what the operator last saved for this run.
2. The ``visible_adjust`` block in ``metadata.json``: the slider values in effect when recording
   started. ``Recorder.start`` writes it once; nothing here ever touches ``metadata.json``.
3. Neutral: runs recorded before this feature have neither.

Reads are tolerant (a missing, corrupt or out-of-range file reads as absent) and writes are atomic
(temp + ``os.replace``), the same pattern as :mod:`flir_research_interface.labels`. The numbers are
checked by :func:`flir_research_interface.analysis.visible_adjust.validate_adjust`. The raw video is
never changed: the adjustment is applied when the video is drawn or analysed.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flir_research_interface.analysis.visible_adjust import NEUTRAL, validate_adjust

logger = logging.getLogger(__name__)

SIDECAR = "visible_adjust.json"
SOURCES = ("sidecar", "recorded", "neutral")


def read_sidecar(run_dir: Path | str) -> dict[str, Any] | None:
    """The saved adjustment (three numbers plus ``saved_utc``), or ``None`` when the file is
    missing, unreadable, not an object, or holds a value outside the limits."""
    path = Path(run_dir) / SIDECAR
    try:
        data = json.loads(path.read_text())
        values = validate_adjust(data)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning("ignoring unreadable %s: %s", path, exc)
        return None
    saved = data.get("saved_utc")
    return {**values, "saved_utc": saved if isinstance(saved, str) else None}


def write_sidecar(run_dir: Path | str, adjust: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and atomically write the run's adjustment; return what was stored.

    Raises:
        ValueError: ``adjust`` is not three in-range numbers. Nothing is written.
    """
    values = validate_adjust(adjust)
    stored: dict[str, Any] = {**values, "saved_utc": datetime.now(timezone.utc).isoformat()}
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=run_dir, prefix=".visible_adjust-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(stored, f)
        os.replace(tmp, run_dir / SIDECAR)
    finally:
        Path(tmp).unlink(missing_ok=True)  # no-op after a successful replace
    return stored


def delete_sidecar(run_dir: Path | str) -> bool:
    """Remove the saved adjustment so the run falls back to its recorded values. ``True`` if a
    file was removed."""
    try:
        (Path(run_dir) / SIDECAR).unlink()
    except FileNotFoundError:
        return False
    return True


def recording_stamp(block: Mapping[str, Any]) -> dict[str, Any]:
    """The ``visible_adjust`` block stored in ``metadata.json``: the three numbers plus the
    ``preset`` and ``based_on`` labels (each a string or ``None``).

    Raises:
        ValueError: a number is missing or out of range, or a label is not a string.
    """
    values = validate_adjust(block)
    labels: dict[str, str | None] = {}
    for key in ("preset", "based_on"):
        label = block.get(key)
        if label is not None and not isinstance(label, str):
            raise ValueError(f"{key} must be a string or null, got {type(label).__name__}")
        labels[key] = label
    return {**values, **labels}


def recorded_adjust(metadata: Mapping[str, Any] | None) -> dict[str, float] | None:
    """The numbers of the stamp in ``metadata``, or ``None`` when it has none or an invalid one."""
    block = (metadata or {}).get("visible_adjust")
    if block is None:
        return None
    try:
        return validate_adjust(block)
    except ValueError as exc:
        logger.warning("ignoring invalid recorded visible_adjust: %s", exc)
        return None


def effective_adjust(
    run_dir: Path | str, metadata: Mapping[str, Any] | None
) -> tuple[dict[str, float], str]:
    """The adjustment to show for a run and where it came from: ``"sidecar"``, ``"recorded"`` or
    ``"neutral"`` (see :data:`SOURCES`)."""
    side = read_sidecar(run_dir)
    if side is not None:
        return {k: side[k] for k in NEUTRAL}, "sidecar"
    recorded = recorded_adjust(metadata)
    if recorded is not None:
        return recorded, "recorded"
    return dict(NEUTRAL), "neutral"


__all__ = [
    "NEUTRAL", "SIDECAR", "SOURCES", "delete_sidecar", "effective_adjust", "read_sidecar",
    "recorded_adjust", "recording_stamp", "write_sidecar",
]
