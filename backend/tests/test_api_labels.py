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


def test_put_title_and_notes_shows_in_the_listing_and_survives_a_star(tmp_path: Path) -> None:
    (tmp_path / "20260911_121421_Run").mkdir()
    c = _client(tmp_path)
    url = "/api/experiments/20260911_121421_Run/labels"
    r = c.put(url, json={"starred": False, "tags": [], "title": "Doped coupon #3",
                         "notes": "PA12 + 2% CB; load retuned at 40 s"}, headers=H)
    assert r.status_code == 200 and r.json()["title"] == "Doped coupon #3"
    c.put(url, json={"starred": True, "tags": ["doped"]}, headers=H)  # no title/notes sent
    run = next(e for e in c.get("/api/experiments").json() if e["name"] == "20260911_121421_Run")
    assert run["title"] == "Doped coupon #3" and run["notes"].startswith("PA12")
    assert run["starred"] is True
    assert (tmp_path / "20260911_121421_Run").is_dir()  # the folder itself is never renamed
