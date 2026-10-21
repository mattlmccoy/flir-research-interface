"""Small API guards for the visible adjustment: strict numbers, the exports listing, the move diff.

* The adjustment bodies take real numbers only: ``true`` or ``"1.0"`` are refused, not coerced.
* A transient ``visible_full_range.mp4.part`` (the playback copy being built) is not an export.
* A run copy that differs only in ``visible_adjust.json`` is a sidecar-only conflict when moved.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flir_research_interface import storage
from flir_research_interface.api.app import create_app

H = {"X-FRI-Client": "1"}
OK = {"exposure_ev": 0.5, "brightness": 0.1, "contrast": 1.5}


def _client(tmp: Path) -> TestClient:
    return TestClient(
        create_app(
            default_backend="simulated", sim_fps=60.0, viz_fps=30.0,
            experiments_root=tmp, min_free_gb=0.0,
        )
    )


def _record_run(c: TestClient, body: dict[str, object] | None = None) -> str:
    devs = c.get("/api/camera/devices").json()
    c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
    r = c.post("/api/recording/start", json={"name": "r", **(body or {})})
    assert r.status_code == 200, r.text
    c.post("/api/recording/stop")
    return str(c.get("/api/experiments").json()[0]["name"])


@pytest.mark.parametrize("bad", [True, "1.0"])
def test_put_visible_adjust_refuses_non_numbers(tmp_path: Path, bad: object) -> None:
    with _client(tmp_path) as c:
        name = _record_run(c)
        r = c.put(f"/api/experiments/{name}/visible-adjust", json={**OK, "contrast": bad},
                  headers=H)
        assert r.status_code in (400, 422), r.text
        assert not (tmp_path / name / "visible_adjust.json").exists()
        ok = c.put(f"/api/experiments/{name}/visible-adjust", json=OK, headers=H)
        assert ok.status_code == 200, ok.text  # a real number (an int too) is still fine
        assert c.put(f"/api/experiments/{name}/visible-adjust",
                     json={**OK, "contrast": 2}, headers=H).status_code == 200


@pytest.mark.parametrize("bad", [True, "1.0"])
def test_recording_stamp_refuses_non_numbers(tmp_path: Path, bad: object) -> None:
    with _client(tmp_path) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        r = c.post("/api/recording/start",
                   json={"name": "bad", "visible_adjust": {**OK, "exposure_ev": bad}})
        assert r.status_code in (400, 422), r.text
        assert [p for p in tmp_path.iterdir() if p.is_dir()] == []


def test_exports_listing_hides_transient_part_files(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        name = _record_run(c)
        exports = tmp_path / name / "exports"
        exports.mkdir(exist_ok=True)
        (exports / "visible_full_range.mp4.part").write_bytes(b"half")
        (exports / "thermal.part.mp4").write_bytes(b"half")
        (exports / "visible_full_range.mp4").write_bytes(b"done")
        names = {e["name"] for e in c.get(f"/api/experiments/{name}").json()["exports"]}
        assert "visible_full_range.mp4" in names
        assert "visible_full_range.mp4.part" not in names
        assert "thermal.part.mp4" not in names


def _run_copy(root: Path, adjust: dict[str, float]) -> Path:
    run = root / "run1"
    (run / "thermal.zarr").mkdir(parents=True)
    (run / "metadata.json").write_text('{"a":1}')
    (run / "thermal.zarr" / "0.0.0").write_bytes(b"x" * 1000)
    (run / "visible_adjust.json").write_text(json.dumps(adjust))
    return run


def test_copy_differing_only_in_the_sidecar_is_a_sidecar_only_conflict(tmp_path: Path) -> None:
    src_root, dst_root = tmp_path / "local", tmp_path / "drive"
    run = _run_copy(src_root, OK)
    shutil.copytree(run, dst_root / "run1")
    (dst_root / "run1" / "visible_adjust.json").write_text(json.dumps({**OK, "contrast": 2.0}))
    with pytest.raises(storage.MoveConflictError, match="only mutable sidecar files differ"):
        storage.move_experiment(run, dst_root)
    assert (run / "visible_adjust.json").is_file()  # both copies kept


def test_copy_differing_in_data_is_not_sidecar_only(tmp_path: Path) -> None:
    """The control: the same setup with a data file changed is reported as data."""
    src_root, dst_root = tmp_path / "local", tmp_path / "drive"
    run = _run_copy(src_root, OK)
    shutil.copytree(run, dst_root / "run1")
    (dst_root / "run1" / "thermal.zarr" / "0.0.0").write_bytes(b"y" * 1000)
    with pytest.raises(storage.MoveConflictError, match="data differs"):
        storage.move_experiment(run, dst_root)
