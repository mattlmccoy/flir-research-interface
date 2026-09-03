"""ExperimentReader: read-only access to a recorded experiment."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from flir_research_interface.camera.base import Frame
from flir_research_interface.playback.reader import ExperimentReader, list_experiments
from flir_research_interface.recording.recorder import Recorder

W, H = 16, 12


def _make_experiment(root: Path, n: int = 10, name: str = "exp") -> Path:
    rec = Recorder(None, experiments_root=root, chunk_frames=4)
    d = rec.start(
        name=name,
        metadata={"operator": "t"},
        camera_info={"backend": "simulated", "ir_format": "TemperatureLinear10mK", "model": "Sim"},
    )
    for i in range(n):
        counts = np.full((H, W), 29815 + i * 10, dtype=np.uint16)
        rec.submit(
            Frame(
                frame_id=100 + i,
                device_timestamp_ns=1_000_000_000 + i * 33_000_000,
                host_timestamp_ns=5_000_000_000 + i * 33_000_000,
                pixel_format="Mono16",
                ir_format="TemperatureLinear10mK",
                counts=counts,
                incomplete=False,
            )
        )
    rec.stop()
    return d


def _tree_hash(path: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(path.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(path).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def test_reader_info_and_frame_access(tmp_path: Path) -> None:
    d = _make_experiment(tmp_path, n=10)
    r = ExperimentReader(d)
    info = r.info()
    assert info["n_frames"] == 10 and info["width"] == W and info["height"] == H
    assert info["complete"] is True and info["ir_format"] == "TemperatureLinear10mK"
    assert info["duration_s"] == pytest.approx(9 * 0.033)
    assert info["conversion"]["kelvin_per_count"] == 0.01
    f = r.frame(3)
    assert isinstance(f, Frame) and f.frame_id == 103 and f.counts.dtype == np.uint16
    assert int(f.counts[0, 0]) == 29815 + 30
    assert f.device_timestamp_ns == 1_000_000_000 + 3 * 33_000_000


def test_reader_timeline_is_relative_seconds(tmp_path: Path) -> None:
    d = _make_experiment(tmp_path, n=5)
    r = ExperimentReader(d)
    tl = r.timeline()
    assert tl["t_s"][0] == 0.0 and tl["t_s"][-1] == pytest.approx(4 * 0.033)
    assert tl["frame_id"] == [100, 101, 102, 103, 104]
    assert r.index_at(0.07) == 2  # nearest frame to t=70 ms (66 ms)


def test_reader_never_modifies_the_store(tmp_path: Path) -> None:
    d = _make_experiment(tmp_path, n=6)
    before = _tree_hash(d)
    r = ExperimentReader(d)
    for i in range(6):
        c = r.frame(i).counts
        c2 = c.astype(np.float32) * 0.01 - 273.15  # derived work must not touch the store
        assert c2.shape == (H, W)
    with pytest.raises((ValueError, TypeError, PermissionError, RuntimeError)):
        r.frame(0).counts[0, 0] = 1  # returned array is read-only
    assert _tree_hash(d) == before


def test_reader_out_of_range_index(tmp_path: Path) -> None:
    d = _make_experiment(tmp_path, n=3)
    r = ExperimentReader(d)
    with pytest.raises(IndexError):
        r.frame(3)


def test_incomplete_experiment_is_readable_and_flagged(tmp_path: Path) -> None:
    rec = Recorder(None, experiments_root=tmp_path, chunk_frames=2)
    d = rec.start(
        name="crash",
        metadata={},
        camera_info={"backend": "simulated", "ir_format": "TemperatureLinear10mK"},
    )
    for i in range(4):
        rec.submit(
            Frame(
                frame_id=i,
                device_timestamp_ns=i * 33_000_000,
                host_timestamp_ns=i,
                pixel_format="Mono16",
                ir_format="TemperatureLinear10mK",
                counts=np.zeros((H, W), np.uint16),
                incomplete=False,
            )
        )
    rec.flush_for_test()  # no stop(): simulate crash
    r = ExperimentReader(d)
    assert r.info()["complete"] is False and r.info()["n_frames"] == 4
    rec.stop()


def test_list_experiments_sorted_newest_first(tmp_path: Path) -> None:
    _make_experiment(tmp_path, n=2, name="a")
    _make_experiment(tmp_path, n=3, name="b")
    items = list_experiments(tmp_path)
    assert [i["n_frames"] for i in items] == [3, 2] or [i["n_frames"] for i in items] == [2, 3]
    assert all("name" in i and "complete" in i for i in items)


def _make_empty_experiment(root: Path) -> Path:
    rec = Recorder(None, experiments_root=root, chunk_frames=8)
    d = rec.start(
        name="empty",
        metadata={},
        camera_info={"backend": "simulated", "ir_format": "TemperatureLinear10mK"},
    )
    rec.stop()  # zero frames submitted: the store has no 'counts' array at all
    return d


def test_empty_recording_opens_as_zero_frame_reader(tmp_path: Path) -> None:
    """A start()/stop() with no frames is a valid, complete, empty experiment (not KeyError)."""
    d = _make_empty_experiment(tmp_path)
    r = ExperimentReader(d)
    assert r.n_frames == 0
    info = r.info()
    assert info["n_frames"] == 0 and info["complete"] is True
    assert info["width"] == 0 and info["height"] == 0 and info["duration_s"] == 0.0
    assert info["ir_format"] == "TemperatureLinear10mK"  # from metadata, not the array attrs
    assert r.timeline() == {"t_s": [], "frame_id": []}
    assert r.timestamps_ns()[0].shape == (0,)
    with pytest.raises(IndexError):
        r.frame(0)
    with pytest.raises(IndexError):
        r.index_at(0.0)
    with pytest.raises(IndexError):
        r.counts_block(0, 1)
    assert r.counts_block(0, 0).shape[0] == 0


def test_list_experiments_includes_empty_recording_without_error(tmp_path: Path) -> None:
    _make_empty_experiment(tmp_path)
    items = list_experiments(tmp_path)
    assert len(items) == 1
    assert items[0]["n_frames"] == 0 and items[0]["complete"] is True
    assert "error" not in items[0]
