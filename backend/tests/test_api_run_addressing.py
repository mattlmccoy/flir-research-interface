"""Run addressing by collection (``?collection=``) and run-keyed jobs and locks.

Runs here are hand-made (``mkdir`` + a distinct ``metadata.json``), not captured from a real
recording: these tests cover which folder a request resolves to and how jobs are keyed, not run
contents, so no handler that needs a reader is exercised.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.collections import RunRef

RUN = "20261102_165506_Run"


def _run(parent: Path, name: str = RUN) -> Path:
    d = parent / name
    d.mkdir(parents=True)
    (d / "metadata.json").write_text(json.dumps({"experiment": {"name": f"{parent.name}/{name}"}}))
    return d


def _client(root: Path, calls: list[list[str]] | None = None) -> TestClient:
    def runner(cmd: list[str]) -> int:
        if calls is not None:
            calls.append(cmd)
        return 0

    app = create_app(
        default_backend="simulated", experiments_root=root, min_free_gb=0.0, reveal_runner=runner
    )
    return TestClient(app)


def _revealed(c: TestClient, query: str) -> str:
    r = c.post(f"/api/experiments/{RUN}/reveal{query}")
    assert r.status_code == 200, r.text
    return str(r.json()["path"])


def test_explicit_collection_resolves_each_copy(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    a = _run(root / "mattmccoy")
    b = _run(root / "rf-sintering")
    c = _client(root)
    assert Path(_revealed(c, "?collection=mattmccoy")) == a.resolve()
    assert Path(_revealed(c, "?collection=rf-sintering")) == b.resolve()


def test_omitted_collection_is_unique_lookup(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    a = _run(root / "mattmccoy")
    c = _client(root)
    assert Path(_revealed(c, "")) == a.resolve()

    _run(root / "rf-sintering")
    r = c.post(f"/api/experiments/{RUN}/reveal")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "mattmccoy" in detail and "rf-sintering" in detail and "?collection=" in detail


def test_empty_collection_means_top_level(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    top = _run(root)
    c = _client(root)
    assert Path(_revealed(c, "?collection=")) == top.resolve()
    assert c.post(f"/api/experiments/{RUN}/reveal?collection=mattmccoy").status_code == 404


def test_invalid_collection_param_400(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    _run(root / "mattmccoy")
    c = _client(root)
    assert c.post(f"/api/experiments/{RUN}/reveal?collection=Bad%20Name").status_code == 400


def test_jobs_are_keyed_per_collection(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    _run(root / "mattmccoy")
    _run(root / "rf-sintering")
    c = _client(root)
    c.app.state.derived_jobs[f"mattmccoy/{RUN}"] = {"state": "running"}  # type: ignore[attr-defined]
    url = f"/api/experiments/{RUN}/export/derived/status"
    assert c.get(url + "?collection=rf-sintering").json() == {"state": "idle"}
    assert c.get(url + "?collection=mattmccoy").json() == {"state": "running"}


def test_post_stop_lock_key_includes_collection(tmp_path: Path) -> None:
    root = tmp_path
    assert RunRef.from_dir(root / "mattmccoy" / "r", [root]).key == "mattmccoy/r"


def test_dot_collection_params_400(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    _run(root / "mattmccoy")
    c = _client(root)
    for bad in ("..", ".x"):
        r = c.post(f"/api/experiments/{RUN}/reveal?collection={bad}")
        assert r.status_code == 400, (bad, r.text)


def test_status_endpoint_409_on_ambiguous_legacy_name(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    _run(root / "mattmccoy")
    _run(root / "rf-sintering")
    r = _client(root).get(f"/api/experiments/{RUN}/export/derived/status")
    assert r.status_code == 409, r.text


def test_top_level_and_collection_copy_409_names_top_level(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    _run(root)
    _run(root / "mattmccoy")
    r = _client(root).post(f"/api/experiments/{RUN}/reveal")
    assert r.status_code == 409
    assert "top level" in r.json()["detail"] and "mattmccoy" in r.json()["detail"]
