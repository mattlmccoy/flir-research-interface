"""Collections routes: list, add and select the per-user / per-project folders under the roots.

Registered by ``create_app``. The selection lives on the operator (``<base>/.collection.json``), so
every browser sees the same one.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from flir_research_interface import storage
from flir_research_interface.collections import (
    RunQuery,
    collection_name_error,
    load_selection,
    run_name_error,
    save_selection,
    scan_root,
)

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


def register_collections_routes(
    app: FastAPI,
    roots: Callable[[], list[tuple[str, Path]]],
    live: Callable[[], bool] = lambda: False,
) -> None:
    """``live()`` is True while a recording or an armed trigger is active (the picker lock)."""

    def _base() -> Path:
        return Path(roots()[0][1])  # the local root is always first

    def _doc() -> dict[str, Any]:
        scans = {lib: scan_root(root) for lib, root in roots()}
        local = set(scans["local"].collections)
        drive = set(scans["drive"].collections) if "drive" in scans else set()
        return {
            "selected": load_selection(_base()),
            "collections": [
                {"name": n, "local": n in local, "drive": n in drive, "offline": False}
                for n in sorted(local | drive)
            ],
            "unsorted": {
                "local": len(scans["local"].runs),
                "drive": len(scans["drive"].runs) if "drive" in scans else 0,
            },
            "unexpected": [
                {"library": lib, "name": n} for lib, s in scans.items() for n in s.unexpected
            ],
            "drive_connected": "drive" in scans,
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
        libs = {lib for lib, _ in roots()}
        if "drive" not in libs and storage.load_storage_config(_base())["drive"]:
            for r in storage.offline_runs(_base()):
                coll = r.get("collection")  # absent from v1 index entries: top level
                seen.add((coll if isinstance(coll, str) and coll else None, str(r["name"])))
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
        return _doc()
