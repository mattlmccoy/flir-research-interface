"""User routes: list and add the people at the bench, and switch who is using the operator.

Registered by ``create_app``. Switching user also selects that user's last collection, so the
switch is refused (409) whenever a collection change would be (recording or armed trigger).
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from flir_research_interface.collections import save_selection
from flir_research_interface.users import (
    UserError,
    add_user,
    public_doc,
    set_current,
    sync_users,
)

__all__ = ["register_users_routes"]


class _AddBody(BaseModel):
    name: str
    collection: str | None = None


class _CurrentBody(BaseModel):
    id: str


def register_users_routes(
    app: FastAPI,
    base: Callable[[], Path],
    live: Callable[[], bool],
    drive: Callable[[], Path | None] = lambda: None,
) -> None:
    """``drive()`` is the connected SSD's ``FLIR-recordings`` root (None when unplugged); every
    read and write syncs the user list with it so the list travels on the drive."""
    @app.get("/api/users")
    def get_users() -> dict[str, Any]:
        return public_doc(sync_users(base(), drive()))

    @app.post("/api/users")
    def post_user(body: _AddBody) -> dict[str, Any]:
        try:
            add_user(base(), body.name, body.collection)
            return public_doc(sync_users(base(), drive()))
        except UserError as exc:
            raise HTTPException(exc.status, str(exc)) from exc

    @app.put("/api/users/current")
    def put_current(body: _CurrentBody) -> dict[str, Any]:
        if live():
            raise HTTPException(
                409, "the user can't change while a recording or armed trigger is active"
            )
        try:
            _doc, pick = set_current(base(), body.id)
        except UserError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        if pick:
            save_selection(base(), pick)
        return public_doc(sync_users(base(), drive()))
