"""Named presets (visible adjustment + thermal camera settings + display) in
``calibration/presets.json``: store, validation, camera-info reading and the routes.

The Spinnaker-shaped input is a real ``GET /api/camera/info`` captured from the A70 on 2026-10-21
(``fixtures/camera_info_a70_20261021.json``); the simulated shape comes from the simulated
camera's own ``camera_info()``. Nothing here writes to a camera.
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from flir_research_interface.analysis.calibration import calibration_dir
from flir_research_interface.api.app import create_app
from flir_research_interface.camera.simulated import SimulatedCameraBackend, UniformScene
from flir_research_interface.presets import (
    PRESETS_FILE,
    PresetExistsError,
    PresetNotFoundError,
    delete_preset,
    load_presets,
    rename_preset,
    save_preset,
    set_last_applied,
    thermal_from_camera_info,
)

FIXTURES = Path(__file__).parent / "fixtures"
ENUMS = {"NUCMode": ["Off", "Automatic"], "IRFrameRate": ["Rate60Hz", "Rate30Hz"]}


def _preset(name: str = "sintering bed", **over: Any) -> dict[str, Any]:
    p: dict[str, Any] = {
        "name": name,
        "visible_adjust": {"exposure_ev": -1.0, "brightness": 0.0, "contrast": 1.4},
        "thermal": {"ObjectEmissivity": 0.95, "CurrentCase": 1, "NUCMode": "Automatic"},
        "display": {"palette": "iron", "range": {"mode": "auto"}},
    }
    p.update(over)
    return p


def _save(root: Path, preset: dict[str, Any]) -> dict[str, Any]:
    return save_preset(root, preset, enum_options=ENUMS, n_cases=3)


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    assert load_presets(root) == {"version": 1, "last_applied": None, "presets": []}
    stored = _save(root, _preset())
    assert (calibration_dir(root) / PRESETS_FILE).is_file()
    doc = load_presets(root)
    assert doc["presets"] == [stored]
    assert stored["thermal"] == {"ObjectEmissivity": 0.95, "CurrentCase": 1, "NUCMode": "Automatic"}
    assert stored["visible_adjust"] == {"exposure_ev": -1.0, "brightness": 0.0, "contrast": 1.4}
    assert stored["saved_utc"].endswith("Z")
    # saving the same name replaces it in place
    _save(root, _preset(display={"palette": "viridis", "range": {"mode": "auto"}}))
    _save(root, _preset("other"))
    again = load_presets(root)["presets"]
    assert [p["name"] for p in again] == ["sintering bed", "other"]
    assert again[0]["display"]["palette"] == "viridis"


def test_preset_rejects_unknown_node_and_bad_enum(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    _save(root, _preset())
    before = (calibration_dir(root) / PRESETS_FILE).read_text()
    bad_thermals = [
        {"ObjectEmissivity": 0.9, "Gain": 3},  # not a writable node
        {"EstimatedTransmission": 0.5},  # read-only camera value
        {"NUCMode": "Sometimes"},  # not in enum_options
        {"IRFrameRate": "Rate15Hz"},  # not offered by this camera
        {"CurrentCase": 3},  # out of range for 3 cases
        {"ObjectEmissivity": 2},  # outside the node's range
    ]
    for thermal in bad_thermals:
        with pytest.raises(ValueError):
            _save(root, _preset("new", thermal=thermal))
    assert (calibration_dir(root) / PRESETS_FILE).read_text() == before  # nothing written
    # without a camera: unknown nodes are still refused, enum values are kept as given
    with pytest.raises(ValueError):
        save_preset(root, _preset("x", thermal={"Gain": 1}), enum_options=None, n_cases=None)
    ok = save_preset(
        root, _preset("x", thermal={"IRFrameRate": "Rate15Hz", "CurrentCase": 2}),
        enum_options=None, n_cases=None,
    )
    assert ok["thermal"] == {"IRFrameRate": "Rate15Hz", "CurrentCase": 2}
    for thermal in ({"CurrentCase": -1}, {"CurrentCase": 1.5}, {"NUCMode": 3}, {"NUCMode": ""},
                    {"ObjectEmissivity": 2}):
        with pytest.raises(ValueError):
            save_preset(root, _preset("y", thermal=thermal), enum_options=None, n_cases=None)


@pytest.mark.parametrize(
    "bad",
    [
        {"name": ""}, {"name": "   "}, {"name": "x" * 61}, {"name": "a/b"}, {"name": "a\\b"},
        {"name": "a\nb"}, {"name": 5},
        {"visible_adjust": {"exposure_ev": 9, "brightness": 0, "contrast": 1}},
        {"visible_adjust": None},
        {"thermal": ["ObjectEmissivity"]},
        {"display": {"palette": "", "range": {"mode": "auto"}}},
        {"display": {"palette": "x" * 41, "range": {"mode": "auto"}}},
        {"display": {"palette": "iron", "range": {"mode": "locked", "min_c": 50, "max_c": 50}}},
        {"display": {"palette": "iron", "range": {"mode": "locked", "min_c": 1}}},
        {"display": {"palette": "iron", "range": {"mode": "locked", "min_c": float("nan"),
                                                   "max_c": 3}}},
        {"display": {"palette": "iron", "range": {"mode": "weird"}}},
        {"display": {"palette": "iron"}},
        {"display": None},
    ],
)
def test_preset_rejects_malformed_fields(tmp_path: Path, bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _save(tmp_path / "e", _preset(**bad))
    assert not (calibration_dir(tmp_path / "e") / PRESETS_FILE).exists()


def test_name_is_stripped_and_locked_range_and_missing_thermal_are_stored(tmp_path: Path) -> None:
    root = tmp_path / "e"
    p = _preset("  padded  ", display={"palette": "iron",
                                        "range": {"mode": "locked", "min_c": 20, "max_c": 250}})
    del p["thermal"]
    stored = _save(root, p)
    assert stored["name"] == "padded" and stored["thermal"] == {}
    assert stored["display"]["range"] == {"mode": "locked", "min_c": 20.0, "max_c": 250.0}


def test_rename_updates_last_applied_and_delete_clears_it(tmp_path: Path) -> None:
    root = tmp_path / "e"
    _save(root, _preset("a"))
    _save(root, _preset("b"))
    set_last_applied(root, "a")
    assert load_presets(root)["last_applied"] == "a"
    rename_preset(root, "a", "a2")
    doc = load_presets(root)
    assert [p["name"] for p in doc["presets"]] == ["a2", "b"] and doc["last_applied"] == "a2"
    assert doc["presets"][0]["thermal"] == _preset()["thermal"]  # content kept
    rename_preset(root, "b", "b2")
    assert load_presets(root)["last_applied"] == "a2"  # another preset's rename leaves it alone
    with pytest.raises(PresetExistsError):
        rename_preset(root, "a2", "b2")
    with pytest.raises(PresetNotFoundError):
        rename_preset(root, "nope", "z")
    with pytest.raises(ValueError):
        rename_preset(root, "a2", "bad/name")
    delete_preset(root, "b2")
    assert load_presets(root)["last_applied"] == "a2"
    delete_preset(root, "a2")
    assert load_presets(root) == {"version": 1, "last_applied": None, "presets": []}
    with pytest.raises(PresetNotFoundError):
        delete_preset(root, "a2")
    with pytest.raises(PresetNotFoundError):
        set_last_applied(root, "gone")
    _save(root, _preset("c"))
    set_last_applied(root, "c")
    set_last_applied(root, None)
    assert load_presets(root)["last_applied"] is None


def test_corrupt_file_reads_as_empty_and_is_kept_aside_on_next_save(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "e"
    path = calibration_dir(root) / PRESETS_FILE
    path.parent.mkdir(parents=True)
    path.write_text('{"version": 1, "presets": [ {"name": "half')  # truncated
    with caplog.at_level(logging.WARNING):
        assert load_presets(root) == {"version": 1, "last_applied": None, "presets": []}
    assert "presets.json" in caplog.text
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        _save(root, _preset("fresh"))
    assert "presets.json" in caplog.text
    assert (path.parent / (PRESETS_FILE + ".corrupt")).read_text().endswith('"half')
    assert [p["name"] for p in load_presets(root)["presets"]] == ["fresh"]
    # a wrong-shaped but valid JSON file is also tolerated
    path.write_text("[1, 2]")
    assert load_presets(root)["presets"] == []
    # one malformed entry is dropped on read; the good one stays
    good = _save(root, _preset("good"))
    doc = json.loads(path.read_text())
    doc["presets"].append({"name": 7})
    doc["last_applied"] = "ghost"
    path.write_text(json.dumps(doc))
    read = load_presets(root)
    assert read["presets"] == [good] and read["last_applied"] is None


def test_thermal_from_camera_info_real_a70_capture(tmp_path: Path) -> None:
    info = json.loads((FIXTURES / "camera_info_a70_20261021.json").read_text())
    thermal, left_out = thermal_from_camera_info(info)
    assert thermal == {
        "ObjectEmissivity": info["object_parameters"]["ObjectEmissivity"],
        "ReflectedTemperature": info["object_parameters"]["ReflectedTemperature"],
        "AtmosphericTemperature": info["object_parameters"]["AtmosphericTemperature"],
        "ObjectDistance": info["object_parameters"]["ObjectDistance"],
        "RelativeHumidity": 0.5,
        "ExtOpticsTemperature": info["object_parameters"]["ExtOpticsTemperature"],
        "ExtOpticsTransmission": 1.0,
        "CurrentCase": 1,
        "NUCMode": "Automatic",
        "IRFrameRate": "Rate30Hz",
    }
    assert left_out == []
    assert "EstimatedTransmission" not in thermal and "UseWindowTemperature" not in thermal
    # the camera's own enum_options and case count accept what it just reported
    stored = save_preset(
        tmp_path / "e", _preset(thermal=thermal), enum_options=info["enum_options"],
        n_cases=info["nodes"]["NumCases"],
    )
    assert stored["thermal"] == thermal


def test_thermal_from_camera_info_leaves_out_none_and_absent() -> None:
    info = json.loads((FIXTURES / "camera_info_a70_20261021.json").read_text())
    info = copy.deepcopy(info)
    info["object_parameters"]["ObjectDistance"] = None
    del info["object_parameters"]["RelativeHumidity"]
    info["nodes"]["NUCMode"] = None
    info["nuc_mode"] = None
    info["active_case"] = None
    del info["nodes"]["CurrentCase"]
    thermal, left_out = thermal_from_camera_info(info)
    assert left_out == ["ObjectDistance", "RelativeHumidity", "CurrentCase", "NUCMode"]
    assert set(thermal).isdisjoint(left_out) and "IRFrameRate" in thermal
    assert thermal_from_camera_info({})[0] == {}
    assert len(thermal_from_camera_info({})[1]) == 10


def test_thermal_from_camera_info_simulated_backend_round_trips(tmp_path: Path) -> None:
    cam = SimulatedCameraBackend(UniformScene(25.0), width=8, height=6, fps=30.0)
    cam.connect(cam.enumerate()[0])
    info = cam.camera_info()
    thermal, left_out = thermal_from_camera_info(info)
    assert left_out == []
    assert thermal["IRFrameRate"] == info["ir_frame_rate"]
    assert thermal["NUCMode"] == info["nuc_mode"]
    assert thermal["CurrentCase"] == info["active_case"]["index"]
    assert thermal["ObjectEmissivity"] == info["object_parameters"]["ObjectEmissivity"]
    assert "EstimatedTransmission" not in thermal
    # what "save current" reads is accepted by the same camera's own limits
    stored = save_preset(
        tmp_path / "e", _preset(thermal=thermal), enum_options=info["enum_options"],
        n_cases=len(info["measurement_cases"]),
    )
    assert stored["thermal"] == thermal


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        default_backend="simulated", sim_fps=60.0, experiments_root=tmp_path / "experiments",
        min_free_gb=0.0,
    )
    return TestClient(app)


def _connect(c: TestClient) -> None:
    devs = c.get("/api/camera/devices").json()
    r = c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
    assert r.status_code == 200, r.text


def test_routes_save_list_rename_apply_delete(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        assert c.get("/api/presets").json() == {"version": 1, "last_applied": None, "presets": []}
        r = c.put("/api/presets/sintering bed", json=_preset())
        assert r.status_code == 200, r.text
        assert [p["name"] for p in r.json()["presets"]] == ["sintering bed"]
        c.put("/api/presets/second", json=_preset("second"))
        # the name in the URL is the key; a body naming another preset is refused
        assert c.put("/api/presets/third", json=_preset("fourth")).status_code == 400
        no_name = _preset()
        del no_name["name"]
        assert c.put("/api/presets/third", json=no_name).status_code == 200
        assert c.put("/api/presets/bad", json=_preset("bad", visible_adjust={})).status_code == 400
        assert c.post("/api/presets/last-applied", json={"name": "ghost"}).status_code == 404
        r = c.post("/api/presets/last-applied", json={"name": "sintering bed"})
        assert r.json()["last_applied"] == "sintering bed"
        r = c.post("/api/presets/sintering bed/rename", json={"new_name": "bed"})
        assert r.status_code == 200 and r.json()["last_applied"] == "bed"
        assert c.post("/api/presets/bed/rename", json={"new_name": "second"}).status_code == 409
        assert c.post("/api/presets/bed/rename", json={"new_name": "a/b"}).status_code == 400
        assert c.post("/api/presets/ghost/rename", json={"new_name": "z"}).status_code == 404
        r = c.delete("/api/presets/bed")
        assert r.status_code == 200 and r.json()["last_applied"] is None
        assert c.delete("/api/presets/bed").status_code == 404
        r = c.post("/api/presets/last-applied", json={"name": None})
        assert r.status_code == 200 and r.json()["last_applied"] is None
        assert [p["name"] for p in c.get("/api/presets").json()["presets"]] == ["second", "third"]


def test_routes_validate_thermal_against_the_connected_camera(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        # no camera: enum values are kept as given, unknown nodes are still refused
        ok = c.put("/api/presets/offline", json=_preset("offline",
                                                        thermal={"IRFrameRate": "Rate99Hz"}))
        assert ok.status_code == 200, ok.text
        assert c.put("/api/presets/g", json=_preset("g", thermal={"Gain": 1})).status_code == 400
        _connect(c)
        bad = c.put("/api/presets/lab", json=_preset("lab", thermal={"IRFrameRate": "Rate99Hz"}))
        assert bad.status_code == 400 and "IRFrameRate" in bad.text
        bad = c.put("/api/presets/lab", json=_preset("lab", thermal={"CurrentCase": 3}))
        assert bad.status_code == 400
        good = c.put("/api/presets/lab", json=_preset("lab", thermal={"CurrentCase": 2}))
        assert good.status_code == 200, good.text
        c.post("/api/camera/disconnect")


def test_current_thermal_route_needs_a_camera_and_never_writes_to_it(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        assert c.get("/api/presets/current-thermal").status_code == 409
        _connect(c)
        before = c.get("/api/camera/info").json()
        r = c.get("/api/presets/current-thermal")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["left_out"] == []
        assert body["thermal"]["CurrentCase"] == before["active_case"]["index"]
        assert body["thermal"]["NUCMode"] == before["nuc_mode"]
        assert "UseWindowTemperature" not in body["thermal"]
        assert c.get("/api/camera/info").json() == before
        c.post("/api/camera/disconnect")
