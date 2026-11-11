"""Collections migration (Task 8): plan read-only, apply only the confirmed names, log, resume.

The base root is derived from ``flir_recordings_listing_20261111.json`` (the 92 real run names):
each run is a hand-made dir holding only ``metadata.json``, with ``._<run>`` AppleDouble siblings
for the first 90 (the recon count). The drive test uses the captured v1 ``.drive-index.json``
fixture with its ``/Volumes/FLIR SSD`` mount prefix rebased onto ``tmp/Drive``.
"""
from __future__ import annotations

import errno
import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from flir_research_interface import storage
from flir_research_interface.api.app import create_app
from flir_research_interface.collections import load_selection
from flir_research_interface.collections_migration import (
    LOG_NAME,
    apply_migration,
    plan_migration,
)

FIXTURES = Path(__file__).parent / "fixtures"
NAMES: list[str] = json.loads((FIXTURES / "flir_recordings_listing_20261111.json").read_text())[
    "runs"
]
V1_INDEX = FIXTURES / "drive_index_v1_20261109.json"
TARGET = "mattmccoy"


def _make_run(parent: Path, name: str, body: str = "{}") -> Path:
    run = parent / name
    run.mkdir(parents=True)
    (run / "metadata.json").write_text(body)
    return run


def _base(tmp_path: Path) -> Path:
    base = tmp_path / "root"
    base.mkdir()
    for i, name in enumerate(NAMES):
        _make_run(base, name)
        if i < 90:
            (base / f"._{name}").write_bytes(b"\x00\x05\x16\x07")
    return base


def _snapshot(base: Path) -> list[Any]:
    out: list[Any] = []
    for dirpath, dirs, files in sorted(os.walk(base)):
        p = Path(dirpath)
        out.append((dirpath, sorted(dirs), sorted(files), p.stat().st_mtime_ns))
        out.extend((f, (p / f).stat().st_mtime_ns) for f in sorted(files))
    return out


def _log(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _client(local: Path) -> TestClient:
    """Use as a context manager: the lifespan sets ``app.state.recorder``, which ``_busy`` reads."""
    return TestClient(
        create_app(
            default_backend="simulated", sim_fps=60.0, experiments_root=local, min_free_gb=0.0
        )
    )


def test_plan_is_read_only_and_complete(tmp_path: Path) -> None:
    base = _base(tmp_path)
    before = _snapshot(base)
    plan = plan_migration(base, TARGET)
    assert _snapshot(base) == before
    assert len(plan.moves) == 92
    assert plan.appledouble == 90
    assert plan.conflicts == ()
    assert plan.already_in_target == 0
    assert all(m.dst == base / TARGET / m.name and m.src == base / m.name for m in plan.moves)


def test_plan_rejects_invalid_target(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        plan_migration(_base(tmp_path), "Bad Name")


def test_apply_moves_confirmed_only_and_logs(tmp_path: Path) -> None:
    base = _base(tmp_path)
    plan = plan_migration(base, TARGET)
    confirm = NAMES[:10]
    log = base / LOG_NAME
    res = apply_migration(plan, confirm=confirm, log_path=log)

    assert sorted(m.name for m in res.moved) == sorted(confirm)
    assert res.failed == () and res.log == log
    assert sorted(p.name for p in (base / TARGET).iterdir()) == sorted(confirm)
    top = [p.name for p in base.iterdir() if p.is_dir() and p.name != TARGET]
    assert len(top) == 82
    assert not any((base / f"._{n}").exists() for n in confirm)
    events = [e["event"] for e in _log(log)]
    assert events == ["start"] + ["move"] * 10 + ["done"]


def test_rerun_finishes_half_done_migration(tmp_path: Path) -> None:
    base = _base(tmp_path)
    apply_migration(plan_migration(base, TARGET), confirm=NAMES[:10], log_path=base / LOG_NAME)

    plan = plan_migration(base, TARGET)
    assert len(plan.moves) == 82 and plan.already_in_target == 10
    res = apply_migration(plan, confirm=[m.name for m in plan.moves], log_path=base / LOG_NAME)
    assert len(res.moved) == 82
    assert plan_migration(base, TARGET).moves == ()
    assert len(list((base / TARGET).iterdir())) == 92
    assert [e["event"] for e in _log(base / LOG_NAME)].count("start") == 2  # appended


def test_conflict_never_overwrites(tmp_path: Path) -> None:
    base = _base(tmp_path)
    name = NAMES[5]
    _make_run(base / TARGET, name, body='{"other": true}')
    files = [base / name / "metadata.json", base / TARGET / name / "metadata.json"]
    before = {p: p.read_bytes() for p in files}

    plan = plan_migration(base, TARGET)
    assert [c[0] for c in plan.conflicts] == [name]
    assert name not in [m.name for m in plan.moves]
    res = apply_migration(plan, confirm=NAMES, log_path=base / LOG_NAME)
    assert name not in [m.name for m in res.moved]
    assert {p: p.read_bytes() for p in before} == before


def test_casefold_clash_is_a_conflict(tmp_path: Path) -> None:
    base = _base(tmp_path)
    name = NAMES[0]
    (base / TARGET / name.upper()).mkdir(parents=True)  # hand-made case-only twin
    plan = plan_migration(base, TARGET)
    assert name in [c[0] for c in plan.conflicts]


def test_destination_appearing_after_plan_is_skipped(tmp_path: Path) -> None:
    base = _base(tmp_path)
    plan = plan_migration(base, TARGET)
    name = NAMES[0]
    _make_run(base / TARGET, name, body='{"late": true}')
    res = apply_migration(plan, confirm=[name], log_path=base / LOG_NAME)
    assert res.moved == () and res.skipped == (name,)
    assert (base / TARGET / name / "metadata.json").read_text() == '{"late": true}'
    assert (base / name).is_dir()


def test_unexpected_and_collections_untouched(tmp_path: Path) -> None:
    base = _base(tmp_path)
    (base / "Old Stuff").mkdir()
    (base / "rf-sintering").mkdir()
    plan = plan_migration(base, TARGET)
    names = [m.name for m in plan.moves]
    assert "Old Stuff" not in names and "rf-sintering" not in names
    assert "Old Stuff" in plan.unexpected


def test_cross_device_rename_fails_not_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _base(tmp_path)
    plan = plan_migration(base, TARGET)
    name = NAMES[0]

    def _exdev(src: Any, dst: Any) -> None:
        raise OSError(errno.EXDEV, "Cross-device link")

    monkeypatch.setattr(os, "rename", _exdev)
    res = apply_migration(plan, confirm=[name], log_path=base / LOG_NAME)
    assert [f[0] for f in res.failed] == [name]
    assert (base / name / "metadata.json").exists()
    assert not (base / TARGET / name).exists()
    assert [e["event"] for e in _log(base / LOG_NAME)] == ["start", "error", "done"]


def test_drive_pass_rewrites_index(tmp_path: Path) -> None:
    local = tmp_path / "local"
    local.mkdir()
    mount = tmp_path / "Drive"
    mount.mkdir()
    storage.register_drive(local, str(mount))
    root = mount / storage.DRIVE_SUBDIR
    idx = json.loads(V1_INDEX.read_text())
    old_prefix = "/Volumes/FLIR SSD"
    text = json.dumps(idx).replace(old_prefix, str(mount))  # rebase the captured paths
    (local / storage.INDEX_NAME).write_text(text)
    names = [r["name"] for r in idx["runs"]]
    for n in names:
        _make_run(root, n)
    with _client(local) as c:

        plan = c.get("/api/collections/migration", params={"volume": "drive", "target": TARGET})
        assert plan.status_code == 200, plan.text
        assert sorted(m["name"] for m in plan.json()["moves"]) == sorted(names)
        body = {"volume": "drive", "target": TARGET, "confirm": names}
        r = c.post("/api/collections/migration", json=body)
        assert r.status_code == 200, r.text
        assert sorted(r.json()["moved"]) == sorted(names)
        assert (root / LOG_NAME).exists()

        out = json.loads((local / storage.INDEX_NAME).read_text())
        assert out["schema"] == 2
        assert {e["collection"] for e in out["runs"]} == {TARGET}
        for e in out["runs"]:
            assert e["path"].endswith(f"/FLIR-recordings/{TARGET}/{e['name']}")
            tp = e.get("thermal_preview")
            if tp:
                assert f"/FLIR-recordings/{TARGET}/{e['name']}/" in tp["path"]


def test_drive_plan_409_when_unplugged(tmp_path: Path) -> None:
    local = tmp_path / "local"
    local.mkdir()
    with _client(local) as c:
        r = c.get("/api/collections/migration", params={"volume": "drive", "target": TARGET})
    assert r.status_code == 409


def test_migration_refuses_while_busy(tmp_path: Path) -> None:
    base = _base(tmp_path)
    with _client(base) as c:
        c.app.state.move_jobs["x"] = {"state": "running"}  # type: ignore[attr-defined]
        body = {"volume": "local", "target": TARGET, "confirm": NAMES}
        r = c.post("/api/collections/migration", json=body)
        assert r.status_code == 409
        assert r.json()["detail"].startswith("operator is busy: ")
        assert r.json()["detail"].endswith("; migration not started")
        assert not (base / TARGET).exists()
        assert not (base / LOG_NAME).exists()


def test_post_validates_target_and_confirm(tmp_path: Path) -> None:
    with _client(_base(tmp_path)) as c:
        bad = {"volume": "local", "target": "Bad Name", "confirm": NAMES[:1]}
        assert c.post("/api/collections/migration", json=bad).status_code == 400
        empty = {"volume": "local", "target": TARGET, "confirm": []}
        assert c.post("/api/collections/migration", json=empty).status_code == 400


def test_local_migration_selects_target(tmp_path: Path) -> None:
    base = _base(tmp_path)
    with _client(base) as c:
        assert load_selection(base) is None
        r = c.post(
            "/api/collections/migration",
            json={"volume": "local", "target": TARGET, "confirm": NAMES[:3]},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert sorted(body["moved"]) == sorted(NAMES[:3]) and body["failed"] == []
        assert body["log"] == str(base / LOG_NAME)
        assert load_selection(base) == TARGET
