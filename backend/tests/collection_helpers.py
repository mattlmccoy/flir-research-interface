"""Test helper: create and select a collection, so Record and Arm are allowed (Task 5)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def select_collection(c: TestClient, name: str = "t") -> None:
    """POST the collection (idempotent) then PUT it as the selection; asserts both succeed."""
    r = c.post("/api/collections", json={"name": name})
    assert r.status_code == 200, r.text
    r = c.put("/api/collections/selected", json={"name": name})
    assert r.status_code == 200, r.text
