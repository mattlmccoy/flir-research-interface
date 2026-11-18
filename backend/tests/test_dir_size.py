"""Run sizes for the experiments list: measured once, re-measured only when a folder changes.

The list used to stat every file of every run on each load (78k files for 102 runs on the
exFAT SSD: 2.5 s idle, 18-28 s while the camera streams)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from flir_research_interface import dir_size
from flir_research_interface.dir_size import DirSizeCache


def _run(tmp_path: Path) -> Path:
    d = tmp_path / "run"
    (d / "thermal.zarr" / "c" / "0").mkdir(parents=True)
    (d / "manifest.json").write_bytes(b"x" * 10)
    for i in range(5):
        (d / "thermal.zarr" / "c" / "0" / str(i)).write_bytes(b"y" * 100)
    return d


def test_size_is_the_sum_of_every_file(tmp_path: Path) -> None:
    assert DirSizeCache().size(_run(tmp_path)) == 510


def test_a_second_listing_does_not_stat_the_files_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = _run(tmp_path)
    cache = DirSizeCache()
    cache.size(d)
    walked: list[str] = []
    real = dir_size._file_bytes
    monkeypatch.setattr(dir_size, "_file_bytes", lambda p: walked.append(p) or real(p))
    assert cache.size(d) == 510
    assert walked == []


def test_a_new_or_removed_file_is_picked_up(tmp_path: Path) -> None:
    d = _run(tmp_path)
    cache = DirSizeCache()
    assert cache.size(d) == 510
    (d / "exports").mkdir()
    (d / "exports" / "roi_series.csv").write_bytes(b"z" * 40)
    assert cache.size(d) == 550
    os.remove(d / "thermal.zarr" / "c" / "0" / "4")
    assert cache.size(d) == 450


def test_a_missing_run_is_zero(tmp_path: Path) -> None:
    assert DirSizeCache().size(tmp_path / "gone") == 0
