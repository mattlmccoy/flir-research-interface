"""Collections routes: list, add and select the per-user / per-project folders under the roots.

Registered by ``create_app``. The selection lives on the operator (``<base>/.collection.json``), so
every browser sees the same one.
"""
from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from flir_research_interface import storage
from flir_research_interface.collections import (
    RunQuery,
    collection_name_error,
    load_renames,
    load_selection,
    record_rename,
    run_name_error,
    save_selection,
    scan_root,
)
from flir_research_interface.collections_migration import (
    LOG_NAME,
    MigrationPlan,
    apply_migration,
    plan_migration,
)
from flir_research_interface.users import note_selection, rename_collection_refs, sync_users

__all__ = ["RunDep", "register_collections_routes", "run_query"]


def run_query(name: str, collection: str | None = None) -> RunQuery:
    """FastAPI dependency for ``/api/experiments/{name}...``: the run name and the optional
    ``?collection=`` ("" = top level, omitted = legacy unique lookup), both validated (400)."""
    if run_name_error(name):
        raise HTTPException(400, "invalid experiment name")
    if collection:
        err = collection_name_error(collection)
        if err:
            raise HTTPException(400, err)
    return RunQuery(name, collection)


RunDep = Annotated[RunQuery, Depends(run_query)]


def _collection_runs(folder: Path) -> list[str]:
    """Run folder names inside a collection (the same children the listing reads)."""
    if not folder.is_dir():
        return []
    return [
        p.name for p in folder.iterdir()
        if p.is_dir() and not p.name.startswith(".") and not p.name.endswith(".partial")
    ]


class _NameBody(BaseModel):
    name: str


class _SelectBody(BaseModel):
    name: str | None = None


class _RenameBody(BaseModel):
    old: str
    new: str


class _MigrationBody(BaseModel):
    volume: str
    target: str
    confirm: list[str]


def _plan_doc(plan: MigrationPlan, volume: str, busy: list[str]) -> dict[str, Any]:
    return {
        "volume": volume,
        "base": str(plan.base),
        "target": plan.target,
        "moves": [{"name": m.name, "src": str(m.src), "dst": str(m.dst)} for m in plan.moves],
        "conflicts": [{"name": n, "reason": r} for n, r in plan.conflicts],
        "appledouble": plan.appledouble,
        "unexpected": list(plan.unexpected),
        "already_in_target": plan.already_in_target,
        "busy": busy,
    }


def register_collections_routes(
    app: FastAPI,
    roots: Callable[[], list[tuple[str, Path]]],
    live: Callable[[], bool] = lambda: False,
    busy: Callable[[], list[str]] = lambda: [],
) -> None:
    """``live()`` is True while a recording or an armed trigger is active (the picker lock);
    ``busy()`` lists why the operator must not be interrupted (a migration is refused then)."""

    def _base() -> Path:
        return Path(roots()[0][1])  # the local root is always first

    def _registered() -> bool:
        return bool(storage.load_storage_config(_base())["drive"])

    def _offline() -> bool:
        """The drive is registered but not connected (its offline index stands in for it)."""
        return "drive" not in dict(roots()) and _registered()

    def _doc() -> dict[str, Any]:
        scans = {lib: scan_root(root) for lib, root in roots()}
        local = set(scans["local"].collections)
        drive = set(scans["drive"].collections) if "drive" in scans else set()
        # unplugged: the drive side is what the offline index last saw, flagged ``offline``
        offline = _offline()
        indexed = storage.offline_collections(_base()) if offline else set()
        return {
            "selected": load_selection(_base()),
            "collections": [
                {
                    "name": n,
                    "local": n in local,
                    "drive": n in drive or n in indexed,
                    "offline": n in indexed,
                }
                for n in sorted(local | drive | indexed)
            ],
            "unsorted": {
                "local": len(scans["local"].runs),
                # unplugged: the top-level runs the offline index last saw (never a false 0)
                "drive": len(scans["drive"].runs) if "drive" in scans
                else len(storage.offline_runs(_base(), collection=None)) if offline else 0,
            },
            "unexpected": [
                {"library": lib, "name": n} for lib, s in scans.items() for n in s.unexpected
            ],
            "drive_connected": "drive" in scans,
            "drive_registered": _registered(),
            "renames": load_renames(_base()),
        }

    @app.get("/api/collections")
    def get_collections() -> dict[str, Any]:
        return _doc()

    @app.get("/api/collections/runs")
    def get_run_locations() -> list[dict[str, str | None]]:
        """Every run's ``{collection, name}`` across local, the connected drive and (while the
        registered drive is unplugged) its offline index; ``collection`` None = top level.
        The browser re-keys its per-run state from this (lib/scopeMigration.ts)."""
        seen: set[tuple[str | None, str]] = set()
        for _lib, root in roots():
            scan = scan_root(root)
            seen.update((None, n) for n in scan.runs)
            for c in scan.collections:
                seen.update((c, n) for n in _collection_runs(root / c))
        if _offline():
            seen.update((r["collection"], str(r["name"])) for r in storage.offline_index(_base()))
        ordered = sorted(seen, key=lambda p: (p[0] or "", p[1]))
        return [{"collection": c, "name": n} for c, n in ordered]

    @app.post("/api/collections")
    def add_collection(body: _NameBody) -> dict[str, Any]:
        err = collection_name_error(body.name)
        if err:
            raise HTTPException(400, err)
        (_base() / body.name).mkdir(parents=True, exist_ok=True)
        return _doc()

    @app.put("/api/collections/selected")
    def select_collection(body: _SelectBody) -> dict[str, Any]:
        if live():
            raise HTTPException(
                409, "the collection can't change while a recording or armed trigger is active"
            )
        name = body.name
        if name:
            err = collection_name_error(name)
            if err:
                raise HTTPException(400, err)
            if name not in {c["name"] for c in _doc()["collections"]}:
                raise HTTPException(404, f"collection {name!r} not found")
        save_selection(_base(), name)
        note_selection(_base(), name)  # the collection joins the current user's list
        sync_users(_base(), dict(roots()).get("drive"))
        return _doc()

    @app.post("/api/collections/rename")
    def rename_collection(body: _RenameBody) -> dict[str, Any]:
        """Rename collection ``old`` to ``new`` on this Mac and the connected SSD (one folder
        rename per volume, rolled back if a later one fails), then every reference to it: the SSD
        index, the selection, each user's list and the rename log the browsers re-key from."""
        old, new = body.old, body.new
        for n in (old, new):
            err = collection_name_error(n)
            if err:
                raise HTTPException(400, err)
        if old == new:
            raise HTTPException(400, "the new name is the same as the old one")
        reasons = busy()
        if live() or reasons:
            why = ", ".join(reasons) or "recording or armed"
            raise HTTPException(409, f"operator is busy: {why}; collection not renamed")
        base = _base()
        if _offline() and old in storage.offline_collections(base):
            raise HTTPException(
                409, f"plug in the SSD first: it holds runs in {old!r} that must be renamed too"
            )
        here = [(lib, Path(root)) for lib, root in roots() if (Path(root) / old).is_dir()]
        if not here:
            raise HTTPException(404, f"collection {old!r} not found")
        for _lib, root in roots():
            clash = storage.destination_clash(Path(root), new)
            if clash is not None:
                raise HTTPException(409, f"{new!r} already exists ({Path(root) / clash})")
        sync_users(base, dict(roots()).get("drive"))  # pull in users known only to the SSD
        done: list[Path] = []
        for _lib, root in here:
            try:
                os.rename(root / old, root / new)
            except OSError as exc:
                for r in reversed(done):  # undo: leave both volumes as they were
                    with contextlib.suppress(OSError):
                        os.rename(r / new, r / old)
                raise HTTPException(500, f"could not rename {root / old}: {exc}") from exc
            done.append(root)
            with contextlib.suppress(OSError):  # exFAT AppleDouble sidecar of the old folder
                (root / f"._{old}").unlink()
        drive_root = dict(roots()).get("drive")
        if drive_root is not None:
            storage.rename_index_collection(base, old, new, drive_root)
        if load_selection(base) == old:
            save_selection(base, new)
        rename_collection_refs(base, old, new)
        sync_users(base, drive_root)
        record_rename(base, old, new, time.time())
        return _doc()

    def _migration_base(volume: str) -> Path:
        """The root a migration runs in: the local root, or ``<mount>/FLIR-recordings`` only."""
        if volume not in ("local", "drive"):
            raise HTTPException(400, "volume must be 'local' or 'drive'")
        root = dict(roots()).get(volume)
        if root is None:
            raise HTTPException(409, "the drive is not connected")
        return Path(root)

    def _plan(volume: str, target: str) -> MigrationPlan:
        base = _migration_base(volume)
        try:
            return plan_migration(base, target)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/collections/migration")
    def get_migration(volume: str, target: str) -> dict[str, Any]:
        """Dry run: what moving ``volume``'s top-level runs into ``target`` would do."""
        return _plan_doc(_plan(volume, target), volume, busy())

    @app.post("/api/collections/migration")
    def post_migration(body: _MigrationBody) -> dict[str, Any]:
        reasons = busy()
        if reasons:
            raise HTTPException(
                409, f"operator is busy: {', '.join(reasons)}; migration not started"
            )
        err = collection_name_error(body.target)
        if err:
            raise HTTPException(400, err)
        if not body.confirm:
            raise HTTPException(400, "confirm lists no runs; nothing to migrate")
        plan = _plan(body.volume, body.target)  # re-plan: the disk may have changed
        res = apply_migration(plan, confirm=body.confirm, log_path=plan.base / LOG_NAME)
        moved = [m.name for m in res.moved]
        if body.volume == "drive":
            storage.reindex_collection(_base(), moved, body.target, plan.base)
        elif load_selection(_base()) is None:
            save_selection(_base(), body.target)
        return {
            "moved": moved,
            "failed": [{"name": n, "error": e} for n, e in res.failed],
            "skipped": list(res.skipped),
            "log": str(res.log),
        }
