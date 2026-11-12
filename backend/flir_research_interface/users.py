"""User profiles: who is at the bench, the shared collections they use, and their project profile.

One file on the operator (``<local root>/.users.json``) so every browser sees the same people,
mirrored to the SSD (``FLIR-recordings/.users.json``) whenever it is connected so the list travels
with the drive (``sync_users``: union by id, newer ``updated`` wins, ``current`` stays local):

    {"current": "mattmccoy",
     "users": [{"id": "mattmccoy", "name": "Matt McCoy", "collections": ["mattmccoy"],
                "last_collection": "mattmccoy", "profile": {...project profile...}}]}

A user does not own folders: ``collections`` names flat collection folders, and two users may list
the same one (a shared project). The ``id`` follows the collection name rules because a new user
gets a collection of the same name by default.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

from .analysis.profile import load_profile, validate_profile
from .collections import collection_name_error
from .storage import _atomic_json

logger = logging.getLogger(__name__)

__all__ = [
    "USERS_FILE",
    "UserError",
    "add_user",
    "current_user",
    "load_users",
    "merge_users",
    "note_selection",
    "public_doc",
    "rename_collection_refs",
    "save_user_profile",
    "set_current",
    "slug_for",
    "sync_users",
    "user_id_error",
    "user_profile",
]

USERS_FILE = ".users.json"
MAX_NAME = 60
_LOCK = threading.Lock()


class UserError(ValueError):
    """A refused user change; ``status`` is the HTTP code the route answers with."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def slug_for(name: str) -> str:
    """The id a display name suggests: ASCII-folded, lowercase, spaces dropped (``Matt McCoy`` ->
    ``mattmccoy``), only ``[a-z0-9_-]`` kept, at most 40 characters."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9_-]", "", folded.lower())[:40]


def user_id_error(uid: str) -> str | None:
    return collection_name_error(uid)


def _valid_user(u: Any) -> bool:
    return (
        isinstance(u, dict)
        and isinstance(u.get("id"), str) and user_id_error(u["id"]) is None
        and isinstance(u.get("name"), str)
        and isinstance(u.get("collections"), list)
        and all(isinstance(c, str) and collection_name_error(c) is None for c in u["collections"])
        and isinstance(u.get("updated", 0), int | float) and not isinstance(u.get("updated"), bool)
    )


def _read(path: Path) -> tuple[dict[str, Any], bool]:
    """The users doc at ``path`` and whether the file may be overwritten (missing or readable).
    An unreadable file reads as empty and is reported not writable, so it is never clobbered."""
    empty: dict[str, Any] = {"current": None, "users": []}
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return empty, True
    except (OSError, ValueError) as exc:
        logger.warning("users file %s unreadable (%s); left untouched", path, exc)
        return empty, False
    if not isinstance(data, dict) or not isinstance(data.get("users"), list):
        logger.warning("users file %s has an unexpected shape; left untouched", path)
        return empty, False
    users = [u for u in data["users"] if _valid_user(u)]
    ids = {u["id"] for u in users}
    cur = data.get("current")
    return {"current": cur if cur in ids else None, "users": users}, True


def load_users(base: Path) -> dict[str, Any]:
    """The users file, or the empty doc when it is missing or malformed (logged)."""
    return _read(base / USERS_FILE)[0]


def merge_users(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Union by id; when both sides have a person, the record with the newer ``updated`` wins (a
    tie keeps ``a``). Order: ``a``'s people, then those only in ``b``."""
    out = {u["id"]: u for u in a}
    for u in b:
        mine = out.get(u["id"])
        if mine is None or float(u.get("updated", 0)) > float(mine.get("updated", 0)):
            out[u["id"]] = u
    order = [u["id"] for u in a] + [u["id"] for u in b if u["id"] not in {x["id"] for x in a}]
    return [out[i] for i in order]


def sync_users(base: Path, drive: Path | None) -> dict[str, Any]:
    """Merge the Mac's list with the SSD's (``drive`` = the connected ``FLIR-recordings`` root, or
    None) and write back whichever side is behind. ``current`` stays on this computer only; each
    user's collections are also created on the SSD so another computer sees them."""
    with _LOCK:
        local, local_ok = _read(base / USERS_FILE)
        if drive is None or not drive.is_dir():
            return local
        remote, remote_ok = _read(drive / USERS_FILE)
        merged = merge_users(local["users"], remote["users"])
        ids = {u["id"] for u in merged}
        doc = {"current": local["current"] if local["current"] in ids else None, "users": merged}
        if local_ok and merged != local["users"]:
            _save(base, doc)
        if remote_ok and merged != remote["users"]:
            _save(drive, {"current": None, "users": merged})
        for u in merged:
            for c in u["collections"]:
                try:
                    (drive / c).mkdir(exist_ok=True)
                except OSError as exc:
                    logger.warning("could not create %s on the drive: %s", drive / c, exc)
        return doc


def _save(base: Path, doc: dict[str, Any]) -> None:
    base.mkdir(parents=True, exist_ok=True)
    _atomic_json(base / USERS_FILE, doc)


def _find(doc: dict[str, Any], uid: str) -> dict[str, Any] | None:
    return next((u for u in doc["users"] if u["id"] == uid), None)


def current_user(base: Path) -> dict[str, Any] | None:
    doc = load_users(base)
    return _find(doc, doc["current"]) if doc["current"] else None


def public_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """What ``GET /api/users`` returns: the profile body stays server-side, only its name shows."""
    return {
        "current": doc["current"],
        "users": [
            {
                "id": u["id"],
                "name": u["name"],
                "collections": list(u["collections"]),
                "last_collection": u.get("last_collection"),
                "profile_name": (u.get("profile") or {}).get("name"),
            }
            for u in doc["users"]
        ],
    }


def add_user(base: Path, name: str, collection: str | None = None) -> dict[str, Any]:
    """Add a person. Their collection is ``collection`` or, by default, a new one named after their
    id; their project profile starts as a copy of the shared lab profile."""
    name = name.strip()
    if not name or len(name) > MAX_NAME:
        raise UserError(f"a name needs 1-{MAX_NAME} characters")
    uid = slug_for(name)
    if not uid:
        raise UserError("the name needs at least one letter or digit")
    err = user_id_error(uid)
    if err:
        raise UserError(err)
    coll = collection or uid
    err = collection_name_error(coll)
    if err:
        raise UserError(err)
    with _LOCK:
        doc = load_users(base)
        if _find(doc, uid):
            raise UserError(f"{name!r} is already a user (id {uid})", 409)
        (base / coll).mkdir(parents=True, exist_ok=True)
        doc["users"].append({
            "id": uid, "name": name, "collections": [coll], "last_collection": coll,
            "profile": load_profile(base), "updated": time.time(),
        })
        _save(base, doc)
        return doc


def set_current(base: Path, uid: str) -> tuple[dict[str, Any], str | None]:
    """Make ``uid`` the current user; returns the doc and the collection to select (their last
    one, else their first, else None)."""
    if user_id_error(uid):
        raise UserError("invalid user id")
    with _LOCK:
        doc = load_users(base)
        u = _find(doc, uid)
        if u is None:
            raise UserError(f"user {uid!r} not found", 404)
        doc["current"] = uid
        _save(base, doc)
    last = u.get("last_collection")
    pick = last if last in u["collections"] else (u["collections"][0] if u["collections"] else None)
    return doc, pick


def note_selection(base: Path, collection: str | None) -> None:
    """A collection was selected: it joins the current user's list and becomes their last one."""
    if not collection:
        return
    with _LOCK:
        doc = load_users(base)
        u = _find(doc, doc["current"]) if doc["current"] else None
        if u is None:
            return
        if collection not in u["collections"]:
            u["collections"].append(collection)
        u["last_collection"] = collection
        u["updated"] = time.time()
        _save(base, doc)


def save_user_profile(base: Path, uid: str, body: Any) -> dict[str, Any]:
    clean = validate_profile(body)
    with _LOCK:
        doc = load_users(base)
        u = _find(doc, uid)
        if u is None:
            raise UserError(f"user {uid!r} not found", 404)
        u["profile"] = clean
        u["updated"] = time.time()
        _save(base, doc)
    return clean


def user_profile(u: dict[str, Any], base: Path) -> dict[str, Any]:
    """The user's project profile, falling back to the shared one if theirs is unreadable."""
    try:
        return validate_profile(u.get("profile"))
    except ValueError:
        return load_profile(base)


def rename_collection_refs(base: Path, old: str, new: str) -> int:
    """Collection ``old`` was renamed: replace it in every user's list and last collection.
    Returns how many users changed (each gets a fresh ``updated`` so the SSD copy follows)."""
    with _LOCK:
        doc = load_users(base)
        changed = 0
        for u in doc["users"]:
            if old not in u["collections"] and u.get("last_collection") != old:
                continue
            seen: list[str] = []
            for c in u["collections"]:
                c2 = new if c == old else c
                if c2 not in seen:
                    seen.append(c2)
            u["collections"] = seen
            if u.get("last_collection") == old:
                u["last_collection"] = new
            u["updated"] = time.time()
            changed += 1
        if changed:
            _save(base, doc)
        return changed
