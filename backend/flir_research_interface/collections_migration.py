"""Move the top-level runs of one root into a collection: plan (read-only), confirm, apply, log.

The plan never touches the disk. Applying moves only the confirmed names that are still valid
(the source exists, the destination does not), one same-volume ``os.rename`` each: a cross-device
move fails rather than copies, and a clash (exact or case-only) is never overwritten. Every event
is appended to a JSON-lines log and flushed, so an interrupted migration is resumed by re-planning.
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from .collections import classify_entry, collection_name_error, scan_root
from .storage import CollectionClashError, destination_clash, move_into_collection

logger = logging.getLogger(__name__)

__all__ = [
    "LOG_NAME",
    "MigrationMove",
    "MigrationPlan",
    "MigrationResult",
    "apply_migration",
    "plan_migration",
]

LOG_NAME = ".collections-migration.log"


@dataclass(frozen=True)
class MigrationMove:
    name: str
    src: Path
    dst: Path


@dataclass(frozen=True)
class MigrationPlan:
    base: Path
    target: str
    moves: tuple[MigrationMove, ...]
    conflicts: tuple[tuple[str, str], ...]  # (run name, reason)
    appledouble: int
    unexpected: tuple[str, ...]
    already_in_target: int


@dataclass(frozen=True)
class MigrationResult:
    moved: tuple[MigrationMove, ...]
    failed: tuple[tuple[str, str], ...]  # (run name, error)
    skipped: tuple[str, ...]
    log: Path


def plan_migration(base: Path, target: str) -> MigrationPlan:
    """Plan moving every top-level run of ``base`` into ``base/target``. Read-only.
    Raises ``ValueError`` for an invalid collection name."""
    err = collection_name_error(target)
    if err:
        raise ValueError(err)
    scan = scan_root(base)
    dst_parent = base / target
    moves: list[MigrationMove] = []
    conflicts: list[tuple[str, str]] = []
    for name in scan.runs:
        clash = destination_clash(dst_parent, name) if dst_parent.is_dir() else None
        if clash is not None:
            conflicts.append((name, f"{target}/ already has {clash}"))
        else:
            moves.append(MigrationMove(name, base / name, dst_parent / name))
    appledouble = sum(1 for m in moves if os.path.lexists(base / f"._{m.name}"))
    already = (
        sum(1 for p in dst_parent.iterdir() if classify_entry(p) == "run")
        if dst_parent.is_dir() else 0
    )
    return MigrationPlan(
        base=base,
        target=target,
        moves=tuple(moves),
        conflicts=tuple(conflicts),
        appledouble=appledouble,
        unexpected=scan.unexpected,
        already_in_target=already,
    )


def _event(log: IO[str], event: str, **fields: Any) -> None:
    """Append one JSON line and push it to disk before the next step."""
    rec = {"ts": datetime.now(UTC).isoformat(timespec="seconds"), "event": event, **fields}
    log.write(json.dumps(rec, default=str) + "\n")
    log.flush()
    os.fsync(log.fileno())


def apply_migration(
    plan: MigrationPlan, *, confirm: Collection[str], log_path: Path
) -> MigrationResult:
    """Rename each confirmed, still-valid move of ``plan``; continue past a failure."""
    wanted = set(confirm)
    moved: list[MigrationMove] = []
    failed: list[tuple[str, str]] = []
    skipped: list[str] = []
    with log_path.open("a") as log:
        _event(log, "start", base=str(plan.base), target=plan.target, confirmed=len(wanted))
        for m in plan.moves:
            if m.name not in wanted:
                continue
            if not m.src.is_dir() or destination_clash(m.dst.parent, m.name) is not None:
                skipped.append(m.name)
                continue
            try:
                move_into_collection(m.src, plan.base, plan.target)
            except (OSError, CollectionClashError) as exc:
                logger.warning("migration: %s not moved: %s", m.name, exc)
                failed.append((m.name, str(exc)))
                _event(log, "error", name=m.name, src=str(m.src), dst=str(m.dst), error=str(exc))
                continue
            moved.append(m)
            _event(log, "move", name=m.name, src=str(m.src), dst=str(m.dst))
        skipped.extend(sorted(wanted - {m.name for m in plan.moves}))
        _event(log, "done", moved=len(moved), failed=len(failed), skipped=len(skipped))
    return MigrationResult(tuple(moved), tuple(failed), tuple(skipped), log_path)
