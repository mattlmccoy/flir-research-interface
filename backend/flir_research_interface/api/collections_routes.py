"""Collections routes: list, add and select the per-user / per-project folders under the roots.

Registered by ``create_app``. The selection lives on the operator (``<base>/.collection.json``), so
every browser sees the same one.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from flir_research_interface.collections import (
    collection_name_error,
    load_selection,
    save_selection,
    scan_root,
)

__all__ = ["register_collections_routes"]


class _NameBody(BaseModel):
    name: str


class _SelectBody(BaseModel):
    name: str | None = None


def register_collections_routes(
    app: FastAPI, roots: Callable[[], list[tuple[str, Path]]]
) -> None:
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

    @app.post("/api/collections")
    def add_collection(body: _NameBody) -> dict[str, Any]:
        err = collection_name_error(body.name)
        if err:
            raise HTTPException(400, err)
        (_base() / body.name).mkdir(parents=True, exist_ok=True)
        return _doc()

    @app.put("/api/collections/selected")
    def select_collection(body: _SelectBody) -> dict[str, Any]:
        name = body.name
        if name:
            err = collection_name_error(name)
            if err:
                raise HTTPException(400, err)
            if name not in {c["name"] for c in _doc()["collections"]}:
                raise HTTPException(404, f"collection {name!r} not found")
        save_selection(_base(), name)
        return _doc()
