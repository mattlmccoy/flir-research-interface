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
from flir_research_interface.users import UserError, add_user, load_users, public_doc, set_current

__all__ = ["register_users_routes"]


class _AddBody(BaseModel):
    name: str
    collection: str | None = None


class _CurrentBody(BaseModel):
    id: str


def register_users_routes(app: FastAPI, base: Callable[[], Path], live: Callable[[], bool]) -> None:
    @app.get("/api/users")
    def get_users() -> dict[str, Any]:
        return public_doc(load_users(base()))

    @app.post("/api/users")
    def post_user(body: _AddBody) -> dict[str, Any]:
        try:
            return public_doc(add_user(base(), body.name, body.collection))
        except UserError as exc:
            raise HTTPException(exc.status, str(exc)) from exc

    @app.put("/api/users/current")
    def put_current(body: _CurrentBody) -> dict[str, Any]:
        if live():
            raise HTTPException(
                409, "the user can't change while a recording or armed trigger is active"
            )
        try:
            doc, pick = set_current(base(), body.id)
        except UserError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        if pick:
            save_selection(base(), pick)
        return public_doc(doc)
