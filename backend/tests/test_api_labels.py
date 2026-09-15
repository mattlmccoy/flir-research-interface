"""Labels API: GET /experiments carries starred/tags; PUT writes the sidecar (per library)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.labels import read_labels

H = {"X-FRI-Client": "1"}


def _client(tmp: Path) -> TestClient:
    return TestClient(
        create_app(default_backend="simulated", experiments_root=tmp, min_free_gb=0.0)
    )


def test_put_labels_writes_sidecar_and_normalizes(tmp_path: Path) -> None:
    (tmp_path / "run1").mkdir()
    c = _client(tmp_path)
    r = c.put(
        "/api/experiments/run1/labels",
        json={"starred": True, "tags": ["Doped", "doped", " x "]},
        headers=H,
    )
    assert r.status_code == 200
    assert r.json() == {"starred": True, "tags": ["Doped", "x"]}
    assert read_labels(tmp_path / "run1") == {"starred": True, "tags": ["Doped", "x"]}


def test_get_experiments_includes_starred_and_tags(tmp_path: Path) -> None:
    (tmp_path / "run1").mkdir()
    c = _client(tmp_path)
    c.put("/api/experiments/run1/labels", json={"starred": True, "tags": ["a"]}, headers=H)
    items = c.get("/api/experiments").json()
    got = next(e for e in items if e["name"] == "run1")
    assert got["starred"] is True and got["tags"] == ["a"]


def test_put_labels_unknown_run_is_404(tmp_path: Path) -> None:
    c = _client(tmp_path)
    r = c.put("/api/experiments/nope/labels", json={"starred": False, "tags": []}, headers=H)
    assert r.status_code == 404
