"""Per-run visible adjustment: sidecar, recording stamp, effective value, routes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from flir_research_interface import storage
from flir_research_interface import visible_adjust_store as store
from flir_research_interface.api.app import create_app

H = {"X-FRI-Client": "1"}

# Shape of a run recorded before this feature, captured (keys, nesting, value types) from
# /Volumes/FLIR SSD/FLIR-recordings/20261020_144402_Run/metadata.json; long values trimmed.
OLD_RUN_METADATA: dict[str, Any] = {
    "format_version": "1",
    "started_utc": "2026-10-20T18:44:02.005067+00:00",
    "experiment": {"name": "Run"},
    "camera": {"backend": "spinnaker", "model": "FLIR A70", "serial": "89903739"},
    "conversion": {"ir_format": "TemperatureLinear10mK", "kelvin_per_count": 0.01},
    "software": {"name": "FLIR Research Interface", "version": "0.4.58"},
    "store": {"path": "thermal.zarr", "zarr_format": 2, "chunk_frames": 32, "every_nth": 1},
    "profile": {"name": "RF heating", "marks": ["RF ON", "RF OFF"]},
    "visible_alignment": {"pairs": [{"ir": [0.30, 0.12], "visible": [0.34, 0.22]}]},
    "rois": [{"id": 94, "kind": "circle", "cx": 147, "cy": 216, "r": 67.0, "name": "powder"}],
    "nuc_hold": {"mode_before": "Automatic", "nuc_before_start": False},
}

SIDECAR_VALUES = {"exposure_ev": 1.0, "brightness": 0.1, "contrast": 1.5}
STAMP = {"exposure_ev": -0.5, "brightness": 0.0, "contrast": 2.0, "preset": "P", "based_on": None}


def _client(tmp: Path) -> TestClient:
    return TestClient(
        create_app(
            default_backend="simulated", sim_fps=60.0, viz_fps=30.0,
            experiments_root=tmp, min_free_gb=0.0,
        )
    )


def test_effective_adjust_prefers_sidecar_then_recorded_then_neutral(tmp_path: Path) -> None:
    meta = {"visible_adjust": STAMP}
    assert store.effective_adjust(tmp_path, meta) == (
        {"exposure_ev": -0.5, "brightness": 0.0, "contrast": 2.0}, "recorded"
    )
    store.write_sidecar(tmp_path, SIDECAR_VALUES)
    assert store.effective_adjust(tmp_path, meta) == (SIDECAR_VALUES, "sidecar")
    assert store.delete_sidecar(tmp_path) is True
    assert store.effective_adjust(tmp_path, meta)[1] == "recorded"
    assert store.delete_sidecar(tmp_path) is False
    assert store.effective_adjust(tmp_path, {}) == (store.NEUTRAL, "neutral")


def test_effective_adjust_neutral_for_old_run(tmp_path: Path) -> None:
    assert "visible_adjust" not in OLD_RUN_METADATA
    assert store.effective_adjust(tmp_path, OLD_RUN_METADATA) == (store.NEUTRAL, "neutral")
    assert store.effective_adjust(tmp_path, None) == (store.NEUTRAL, "neutral")
    bad = {"visible_adjust": {"exposure_ev": 99, "brightness": 0, "contrast": 1}}
    assert store.effective_adjust(tmp_path, bad) == (store.NEUTRAL, "neutral")


def test_write_sidecar_atomic_and_validated(tmp_path: Path) -> None:
    stored = store.write_sidecar(tmp_path, {**SIDECAR_VALUES, "preset": "ignored"})
    assert {k: stored[k] for k in SIDECAR_VALUES} == SIDECAR_VALUES
    assert isinstance(stored["saved_utc"], str) and "preset" not in stored
    on_disk = json.loads((tmp_path / store.SIDECAR).read_text())
    assert on_disk == stored
    assert [p.name for p in tmp_path.iterdir()] == [store.SIDECAR]  # no temp file left behind
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ValueError):
        store.write_sidecar(other, {"exposure_ev": 9.0, "brightness": 0.0, "contrast": 1.0})
    assert list(other.iterdir()) == []
    with pytest.raises(ValueError):
        store.write_sidecar(tmp_path, {"exposure_ev": 0.0})
    assert json.loads((tmp_path / store.SIDECAR).read_text()) == stored  # old file untouched


def test_tolerant_read_of_corrupt_sidecar(tmp_path: Path) -> None:
    assert store.read_sidecar(tmp_path) is None
    for text in ("", "{not json", "[1, 2]", '{"exposure_ev": 50, "brightness": 0, "contrast": 1}'):
        (tmp_path / store.SIDECAR).write_text(text)
        assert store.read_sidecar(tmp_path) is None
        assert store.effective_adjust(tmp_path, {"visible_adjust": STAMP})[1] == "recorded"


def test_recording_stamp_validates_and_keeps_labels() -> None:
    assert store.recording_stamp(STAMP) == STAMP
    assert store.recording_stamp({**SIDECAR_VALUES})["preset"] is None
    with pytest.raises(ValueError):
        store.recording_stamp({"exposure_ev": 0.0, "brightness": 0.9, "contrast": 1.0})


def test_mutable_paths_include_sidecar() -> None:
    assert storage.MUTABLE_PATHS == ("labels.json", "visible_adjust.json", "exports/*")


def test_recording_start_stamps_visible_adjust(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        r = c.post("/api/recording/start", json={"name": "stamped", "visible_adjust": STAMP})
        assert r.status_code == 200, r.text
        assert c.post("/api/recording/stop").status_code == 200
        run = next(p for p in tmp_path.iterdir() if p.is_dir())
        meta = json.loads((run / "metadata.json").read_text())
        assert meta["visible_adjust"] == STAMP
        assert "profile" in meta  # the other extra blocks are still merged
        info = c.get(f"/api/experiments/{run.name}").json()
        assert info["visible_adjust_recorded"] == STAMP
        assert info["visible_adjust"] == {
            "exposure_ev": -0.5, "brightness": 0.0, "contrast": 2.0, "source": "recorded"
        }
        bad = c.post(
            "/api/recording/start",
            json={"name": "bad", "visible_adjust": {**STAMP, "contrast": 99.0}},
        )
        assert bad.status_code == 400 and "contrast" in bad.text


def test_recording_without_visible_adjust_has_no_block(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        assert c.post("/api/recording/start", json={"name": "plain"}).status_code == 200
        c.post("/api/recording/stop")
        run = next(p for p in tmp_path.iterdir() if p.is_dir())
        assert "visible_adjust" not in json.loads((run / "metadata.json").read_text())
        info = c.get(f"/api/experiments/{run.name}").json()
        assert info["visible_adjust_recorded"] is None
        assert info["visible_adjust"]["source"] == "neutral"


def _record_run(c: TestClient) -> str:
    devs = c.get("/api/camera/devices").json()
    c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
    assert c.post("/api/recording/start", json={"name": "r"}).status_code == 200
    c.post("/api/recording/stop")
    return str(c.get("/api/experiments").json()[0]["name"])


def test_put_and_delete_visible_adjust_route(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        name = _record_run(c)
        url = f"/api/experiments/{name}/visible-adjust"
        meta_before = (tmp_path / name / "metadata.json").read_bytes()
        r = c.put(url, json={**SIDECAR_VALUES, "library": "local"}, headers=H)
        assert r.status_code == 200, r.text
        assert {k: r.json()[k] for k in SIDECAR_VALUES} == SIDECAR_VALUES
        assert (tmp_path / name / store.SIDECAR).is_file()
        info = c.get(f"/api/experiments/{name}").json()
        assert info["visible_adjust"] == {**SIDECAR_VALUES, "source": "sidecar"}
        assert (tmp_path / name / "metadata.json").read_bytes() == meta_before  # never rewritten
        bad = c.put(url, json={**SIDECAR_VALUES, "brightness": 2.0}, headers=H)
        assert bad.status_code == 400 and "brightness" in bad.text
        assert json.loads((tmp_path / name / store.SIDECAR).read_text())["brightness"] == 0.1
        assert c.put(url, json={**SIDECAR_VALUES, "library": "drive"}, headers=H).status_code == 404
        assert c.delete(url, params={"library": "drive"}, headers=H).status_code == 404
        assert c.delete(url, params={"library": "local"}, headers=H).status_code == 200
        assert not (tmp_path / name / store.SIDECAR).exists()
        assert c.get(f"/api/experiments/{name}").json()["visible_adjust"]["source"] == "neutral"
        assert c.delete(url, headers=H).status_code == 200  # nothing to delete is not an error


def test_put_visible_adjust_unknown_run_and_bad_name(tmp_path: Path) -> None:
    c = _client(tmp_path)
    ok = {"exposure_ev": 0.0, "brightness": 0.0, "contrast": 1.0}
    assert c.put("/api/experiments/nope/visible-adjust", json=ok, headers=H).status_code == 404
    assert c.put("/api/experiments/a%5Cb/visible-adjust", json=ok, headers=H).status_code == 400
    assert c.delete("/api/experiments/a%5Cb/visible-adjust", headers=H).status_code == 400
    assert os.listdir(tmp_path) == []
