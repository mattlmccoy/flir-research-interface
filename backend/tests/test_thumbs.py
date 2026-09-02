"""``fri-thumbs`` CLI: skip non-experiment dirs, up-to-date/force, missing root."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from flir_research_interface.camera.base import Frame
from flir_research_interface.recording.recorder import Recorder
from flir_research_interface.thumbs import main


def _exp(root: Path, n: int = 6) -> Path:
    rec = Recorder(None, experiments_root=root, chunk_frames=4)
    d = rec.start(
        name="pv",
        metadata={},
        camera_info={"backend": "simulated", "ir_format": "TemperatureLinear10mK"},
    )
    for i in range(n):
        rec.submit(
            Frame(
                frame_id=i,
                device_timestamp_ns=i * 33_000_000,
                host_timestamp_ns=i,
                pixel_format="Mono16",
                ir_format="TemperatureLinear10mK",
                counts=np.full((8, 10), 30000 + i, np.uint16),
                incomplete=False,
            )
        )
    rec.stop()
    return d


def test_main_generates_previews_and_skips_non_experiment_entries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    d = _exp(tmp_path)
    stray_dir = tmp_path / "not_an_experiment"
    stray_dir.mkdir()
    (tmp_path / "stray_file.txt").write_text("hello")

    rc = main([str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert f"{d.name}:" in out
    assert f"{stray_dir.name}: skipped (not an experiment)" in out
    assert (d / "preview.png").is_file() and (d / "keyframes.png").is_file()


def test_main_second_run_reports_up_to_date(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    d = _exp(tmp_path)
    main([str(tmp_path)])
    capsys.readouterr()

    rc = main([str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert f"{d.name}: up to date" in out


def test_main_force_regenerates(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    d = _exp(tmp_path)
    main([str(tmp_path)])
    capsys.readouterr()

    rc = main([str(tmp_path), "--force"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "up to date" not in out
    assert f"{d.name}:" in out


def test_main_missing_root_returns_2(tmp_path: Path) -> None:
    assert main([str(tmp_path / "nope")]) == 2


def test_main_single_experiment_dir_invocation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    d = _exp(tmp_path)

    rc = main([str(d)])
    out = capsys.readouterr().out

    assert rc == 0
    assert f"{d.name}:" in out
    assert (d / "preview.png").is_file()
