"""Project profile: which metadata fields the record panel asks for and which mark buttons it
shows. Stored on the operator (calibration/profile.json) so every browser sees the same one;
recordings stamp the profile name. The tool itself assumes nothing about the experiment."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flir_research_interface.analysis.calibration import calibration_dir
from flir_research_interface.analysis.profile import (
    DEFAULT_PROFILE,
    load_profile,
    save_profile,
    validate_profile,
)
from flir_research_interface.api.app import create_app


def test_default_profile_is_generic() -> None:
    p = DEFAULT_PROFILE
    assert p["name"] == "default"
    keys = [f["key"] for f in p["fields"]]
    assert "operator" in keys and "sample_id" in keys and "notes" in keys
    assert not any("rf" in k for k in keys)
    assert [m["label"] for m in p["marks"]] == ["event A", "event B"]


def test_validate_and_roundtrip(tmp_path: Path) -> None:
    prof = {
        "name": "RF heating",
        "fields": [
            {"key": "material", "label": "Material", "type": "text"},
            {"key": "rf_forward_power_w", "label": "RF fwd (W)", "type": "number"},
        ],
        "marks": [{"label": "RF ON", "key": "r"}, {"label": "RF OFF", "key": "f"}],
    }
    clean = validate_profile(prof)
    assert clean == prof
    root = tmp_path / "experiments"  # calibration/ lives beside the experiments root
    save_profile(root, clean)
    assert (calibration_dir(root) / "profile.json").is_file()
    assert load_profile(root) == prof
    assert load_profile(tmp_path / "a" / "nowhere") == DEFAULT_PROFILE
    for bad in (
        {"name": "", "fields": [], "marks": []},
        {"name": "x", "fields": [{"key": "bad key", "label": "b", "type": "text"}], "marks": []},
        {"name": "x", "fields": [{"key": "a", "label": "b", "type": "date"}], "marks": []},
        {"name": "x", "fields": [], "marks": [{"label": "", "key": "r"}]},
        {"name": "x", "fields": [], "marks": [{"label": "a", "key": "rr"}]},
        {"name": "x", "fields": [{"key": "a", "label": "b", "type": "text"}] * 2, "marks": []},
    ):
        with pytest.raises(ValueError):
            validate_profile(bad)


def test_profile_api_and_recording_stamp(tmp_path: Path) -> None:
    app = create_app(
        default_backend="simulated",
        sim_fps=60.0,
        experiments_root=tmp_path / "experiments",
        min_free_gb=0.0,
    )
    with TestClient(app) as c:
        assert c.get("/api/profile").json()["name"] == "default"
        prof = {
            "name": "RF heating",
            "fields": [{"key": "material", "label": "Material", "type": "text"}],
            "marks": [{"label": "RF ON", "key": "r"}, {"label": "RF OFF", "key": "f"}],
        }
        r = c.put("/api/profile", json=prof, headers={"X-FRI-Client": "1"})
        assert r.status_code == 200, r.text
        assert c.get("/api/profile").json() == prof
        assert (
            c.put("/api/profile", json={"name": ""}, headers={"X-FRI-Client": "1"}).status_code
            == 400
        )
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        d = Path(
            c.post("/api/recording/start", json={"name": "p", "nuc_hold": False}).json()[
                "experiment_dir"
            ]
        )
        time.sleep(0.1)
        c.post("/api/recording/stop")
        c.post("/api/camera/disconnect")
        meta = json.loads((d / "metadata.json").read_text())
        assert meta["profile"] == {"name": "RF heating", "marks": ["RF ON", "RF OFF"]}
