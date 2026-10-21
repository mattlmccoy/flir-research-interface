"""The visible-sample runner's failure paths: nothing half-written, nothing stale.

The helpers and clip kinds are described in tests/visible_sample_helpers.py.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from flir_research_interface.analysis import visible_sample_io as vio
from flir_research_interface.analysis import visible_sample_run as vsr
from tests import visible_sample_helpers as vh
from tests.visible_sample_helpers import (
    experiment,
    exported,
    needs_ffmpeg,
    run_analysis,
)

# The shared fixtures, bound here so that pytest finds them in this module (importing them by name
# would make ruff report F811 wherever a test takes one as an argument).
real, short_clip, fixed_threshold = vh.real, vh.short_clip, vh.fixed_threshold


# -- failures: no half-written files, no stale results ----------------------------------------


@needs_ffmpeg
def test_runner_writes_atomically_and_overwrites(
    tmp_path: Path,
    real: dict[str, Any],
    short_clip: Path,
    fixed_threshold: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    d = experiment(tmp_path, real, [short_clip])
    exports = d / "exports"
    csv_path, mp4_path, png_path = (
        exports / "visible_sample.csv",
        exports / "visible_sample_closeup.mp4",
        exports / "visible_sample_plot.png",
    )
    first = run_analysis(d)
    assert first["status"] == "ok"
    good_csv = csv_path.read_text()
    csv_path.write_text("stale")
    mp4_path.write_bytes(b"stale")
    assert run_analysis(d)["status"] == "ok"
    assert csv_path.read_text() == good_csv and mp4_path.stat().st_size > 5  # replaced
    assert not list(exports.glob("*.part"))
    # an explicit ffmpeg that is not an executable file: skipped, and nothing stale is left
    png_path.write_bytes(b"stale")
    (exports / "visible_sample.csv.part").write_text("half")
    out = run_analysis(d, ffmpeg="/nonexistent")
    assert out["status"] == "skipped" and out["reason"] == "ffmpeg not found"
    assert exported(d) == ["visible_sample.json"]
    # a decode that dies mid-stream: failed, with no half-written or older results left
    assert run_analysis(d)["status"] == "ok"
    png_path.write_bytes(b"stale")
    real_decode = vio.decode_luma

    def dies_mid_stream(*args: Any, **kw: Any) -> Iterator[Any]:
        for i, frame in enumerate(real_decode(*args, **kw)):
            if i == 5:
                raise RuntimeError("decoder died")
            yield frame

    monkeypatch.setattr(vio, "decode_luma", dies_mid_stream)
    out = run_analysis(d)
    assert out["status"] == "failed" and out["reason"] == "RuntimeError: decoder died"
    assert exported(d) == ["visible_sample.json"]
    assert json.loads((exports / "visible_sample.json").read_text()) == out


@needs_ffmpeg
def test_runner_closeup_failure_leaves_nothing_partial(
    tmp_path: Path,
    real: dict[str, Any],
    short_clip: Path,
    fixed_threshold: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fails(*args: Any, **kw: Any) -> None:
        args[2].write_bytes(b"half")  # the .part it was given
        raise RuntimeError("encoder died")

    monkeypatch.setattr(vsr, "_encode_closeup", fails)
    d = experiment(tmp_path, real, [short_clip])
    out = run_analysis(d)
    assert out["status"] == "failed" and out["reason"] == "RuntimeError: encoder died"
    assert exported(d) == ["visible_sample.json"]  # the CSV that was ready is not kept either


@needs_ffmpeg
def test_runner_frame_count_mismatch_fails(
    tmp_path: Path,
    real: dict[str, Any],
    short_clip: Path,
    fixed_threshold: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_probe = vio.probe

    def one_extra_packet(*args: Any, **kw: Any) -> Any:
        probe = real_probe(*args, **kw)
        return type(probe)(
            width=probe.width,
            height=probe.height,
            pts_s=np.append(probe.pts_s, probe.pts_s[-1] + 0.1),
            keyframe=np.append(probe.keyframe, False),
        )

    monkeypatch.setattr(vio, "probe", one_extra_packet)
    d = experiment(tmp_path, real, [short_clip])
    out = run_analysis(d)
    assert out["status"] == "failed"
    assert "frame count" in out["reason"]
    assert exported(d) == ["visible_sample.json"]
