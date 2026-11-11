"""Collection model: name rules, RunRef, directory classification, selection store.

Fixtures: ``flir_recordings_listing_20261111.json`` holds the 92 real run names captured from the
Mac-side ``.drive-index.json``. Shapes marked "hand-made" below are synthesised, not captured.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from flir_research_interface.collections import (
    RunRef,
    classify_entry,
    collection_name_error,
    load_selection,
    run_name_error,
    save_selection,
    scan_root,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("ok", ["mattmccoy", "rf-sintering", "a", "x_1", "a" * 40])
def test_valid_collection_names(ok: str) -> None:
    assert collection_name_error(ok) is None


@pytest.mark.parametrize("bad", ["", "a" * 41, "Matt", "has space", ".hidden", "a/b",
                                 "20261102_165506_Run", "20261102_165506", "FLIR-recordings",
                                 "abc\n", "abc\r\n"])
def test_rejected_collection_names(bad: str) -> None:
    assert collection_name_error(bad)


@pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "a\\b"])
def test_rejected_run_names(bad: str) -> None:
    assert run_name_error(bad)


def test_accepted_run_name() -> None:
    assert run_name_error("20261102_165506_Run One") is None


def test_run_ref_key_and_from_dir(tmp_path: Path) -> None:
    assert RunRef("mattmccoy", "r").key == "mattmccoy/r" and RunRef(None, "r").key == "r"
    assert RunRef("mattmccoy", "r").rel() == Path("mattmccoy") / "r"
    assert RunRef(None, "r").rel() == Path("r")
    assert RunRef.from_dir(tmp_path / "mattmccoy" / "r", [tmp_path]) == RunRef("mattmccoy", "r")
    assert RunRef.from_dir(tmp_path / "r", [tmp_path]) == RunRef(None, "r")


def test_classify_entry(tmp_path: Path) -> None:
    # hand-made shapes
    (tmp_path / "20261102_165506_Run").mkdir()
    (tmp_path / "legacy").mkdir()
    (tmp_path / "legacy" / "metadata.json").write_text("{}")
    (tmp_path / "mattmccoy").mkdir()
    (tmp_path / "Old Stuff").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".Trashes").mkdir()
    (tmp_path / "x.part").mkdir()
    (tmp_path / "file.txt").write_text("x")
    kinds = {p.name: classify_entry(p) for p in tmp_path.iterdir()}
    assert kinds == {
        "20261102_165506_Run": "run", "legacy": "run", "mattmccoy": "collection",
        "Old Stuff": "unexpected", ".hidden": "skip", ".Trashes": "skip",
        "x.part": "skip", "file.txt": "skip",
    }


def test_classify_entry_store_makes_a_run(tmp_path: Path) -> None:
    # hand-made shape: a hand-renamed / legacy run with only thermal.zarr must never read as a
    # collection (that would hide it), whatever its name looks like.
    from flir_research_interface.recording.recorder import STORE_NAME

    (tmp_path / "renamed").mkdir()
    (tmp_path / "renamed" / STORE_NAME).mkdir()
    (tmp_path / "Odd Name").mkdir()
    (tmp_path / "Odd Name" / STORE_NAME).mkdir()
    assert classify_entry(tmp_path / "renamed") == "run"
    assert classify_entry(tmp_path / "Odd Name") == "run"


def test_store_name_matches_recorder_without_importing_it() -> None:
    # collections.py is the pure model: it keeps its own STORE_NAME literal (no recorder/zarr
    # import, no cycle when the recorder uses collections) and it must equal the recorder's.
    import subprocess
    import sys

    from flir_research_interface import collections as coll
    from flir_research_interface.recording.recorder import STORE_NAME

    assert coll.STORE_NAME == STORE_NAME
    probe = (
        "import sys, flir_research_interface.collections; "
        "print('flir_research_interface.recording.recorder' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_scan_missing_root(tmp_path: Path) -> None:
    scan = scan_root(tmp_path / "nope")
    assert (scan.collections, scan.runs, scan.unexpected) == ((), (), ())


def test_scan_real_ssd_shape(tmp_path: Path) -> None:
    # runs: the 92 real names (captured fixture); the rest is hand-made: "._<run>" AppleDouble
    # siblings for 90 of them (count from the 2026-11-11 recon, which 90 is synthesised),
    # .Trashes, a lab-storage staging dir, one collection and one unexpected folder.
    names = json.loads((FIXTURES / "flir_recordings_listing_20261111.json").read_text())["runs"]
    assert len(names) == 92
    for n in names:
        (tmp_path / n).mkdir()
    for n in names[:90]:
        (tmp_path / f"._{n}").write_text("")
    (tmp_path / ".Trashes").mkdir()
    (tmp_path / ".lab-storage-partial.20261102_165506_x").mkdir()
    (tmp_path / "mattmccoy").mkdir()
    (tmp_path / "Old Stuff").mkdir()
    scan = scan_root(tmp_path)
    assert len(scan.runs) == 92 and scan.runs == tuple(sorted(names))
    assert scan.collections == ("mattmccoy",)
    assert scan.unexpected == ("Old Stuff",)


def test_selection_roundtrip_and_malformed(tmp_path: Path) -> None:
    assert load_selection(tmp_path) is None
    save_selection(tmp_path, "mattmccoy")
    assert load_selection(tmp_path) == "mattmccoy"
    save_selection(tmp_path, "")
    assert load_selection(tmp_path) == ""
    (tmp_path / ".collection.json").write_text("{nope")
    assert load_selection(tmp_path) is None
    (tmp_path / ".collection.json").write_text('{"selected": "Bad Name"}')
    assert load_selection(tmp_path) is None
    with pytest.raises(ValueError):
        save_selection(tmp_path, "Bad Name")


def test_save_selection_creates_base(tmp_path: Path) -> None:
    save_selection(tmp_path / "new", "a")
    assert load_selection(tmp_path / "new") == "a"


def test_save_selection_none_roundtrip(tmp_path: Path) -> None:
    save_selection(tmp_path, None)
    assert json.loads((tmp_path / ".collection.json").read_text()) == {"selected": None}
    assert load_selection(tmp_path) is None
