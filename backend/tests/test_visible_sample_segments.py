"""The visible-sample runner's inputs: skips, and segments on the thermal time axis.

A run that cannot be analysed is skipped with a reason; segments that are missing from disk are
reported and the rest analysed; each segment's times are placed by its own start. The helpers and
clip kinds are described in tests/visible_sample_helpers.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from flir_research_interface.analysis import visible_sample_run as vsr
from tests import visible_sample_helpers as vh
from tests.visible_sample_helpers import (
    T_START_S,
    csv_rows,
    experiment,
    exported,
    needs_ffmpeg,
    run_analysis,
)

# The shared fixtures, bound here so that pytest finds them in this module (importing them by name
# would make ruff report F811 wherever a test takes one as an argument).
real, clip, short_clip, fixed_threshold = vh.real, vh.clip, vh.short_clip, vh.fixed_threshold


# -- skips: the video cannot be analysed, and the JSON says why --------------------------------


def _assert_skipped(out: dict[str, Any], d: Path, reason: str) -> None:
    assert out["status"] == "skipped"
    assert out["reason"] == reason
    assert out["files"] == ["visible_sample.json"]
    assert "events" not in out and "coverage" not in out  # never an empty "no events"
    assert exported(d) == ["visible_sample.json"]
    assert json.loads((d / "exports" / "visible_sample.json").read_text()) == out


def test_runner_skips_without_visible(tmp_path: Path, real: dict[str, Any]) -> None:
    d = experiment(tmp_path, real)
    _assert_skipped(run_analysis(d), d, "no visible video")


@pytest.mark.parametrize("n_listed", [1, 2])
def test_runner_skips_when_every_listed_segment_is_missing(
    tmp_path: Path, real: dict[str, Any], n_listed: int
) -> None:
    dummy = tmp_path / "dummy.mp4"
    dummy.write_bytes(b"not a video")
    d = experiment(tmp_path, real, [dummy] * n_listed)
    for path in d.glob("visible*.mp4"):
        path.unlink()
    _assert_skipped(run_analysis(d), d, "no visible video")


def test_runner_skips_without_alignment(tmp_path: Path, real: dict[str, Any]) -> None:
    dummy = tmp_path / "dummy.mp4"
    dummy.write_bytes(b"not a video")
    d = experiment(tmp_path, real, [dummy], alignment=False)
    _assert_skipped(run_analysis(d), d, "no visible alignment")


def test_runner_skips_without_sample_roi(tmp_path: Path, real: dict[str, Any]) -> None:
    dummy = tmp_path / "dummy.mp4"
    dummy.write_bytes(b"not a video")
    rois = [r for r in real["rois"] if "sample" not in r["name"]]
    d = experiment(tmp_path, real, [dummy], rois=rois)
    _assert_skipped(run_analysis(d), d, "no sample ROI (name containing 'sample')")


@needs_ffmpeg
def test_runner_skips_when_roi_outside_frame(
    tmp_path: Path, real: dict[str, Any], clip: Path
) -> None:
    far = {"id": 1, "kind": "polygon", "name": "sample",
           "points": [[-900, -900], [-850, -900], [-850, -850], [-900, -850]]}  # fmt: skip
    d = experiment(tmp_path, real, [clip], rois=[far])
    _assert_skipped(run_analysis(d), d, "sample ROI maps outside the visible frame")


@needs_ffmpeg
@pytest.mark.parametrize(
    "h_matrix",
    [
        [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],  # singular
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [4.0, 0.0, 1.0]],  # sends the ROI through infinity
    ],
)
def test_runner_skips_with_invalid_alignment(
    tmp_path: Path, real: dict[str, Any], clip: Path, h_matrix: list[list[float]]
) -> None:
    sample = {"id": 1, "kind": "polygon", "name": "sample",
              "points": [[100, 100], [200, 100], [200, 200], [100, 200]]}  # fmt: skip
    d = experiment(tmp_path, real, [clip], rois=[sample], alignment={"H": h_matrix})
    _assert_skipped(run_analysis(d), d, "visible alignment is invalid")


@needs_ffmpeg
def test_runner_reports_a_missing_segment_and_what_it_analysed(
    tmp_path: Path,
    real: dict[str, Any],
    short_clip: Path,
    fixed_threshold: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """visible.json lists two segments but the second file is not on disk: the run is analysed
    from the first, and the JSON names what was read and what was not."""
    d = experiment(tmp_path, real, [short_clip, short_clip])
    (d / "visible_001.mp4").unlink()
    with caplog.at_level("WARNING", logger=vsr.logger.name):
        out = run_analysis(d, closeup=False)
    assert out["status"] == "ok", out
    assert out["missing"] == ["visible_001.mp4"]
    assert out["segments"] == [
        {
            "index": 0,
            "file": "visible.mp4",
            "t_start_s": pytest.approx(T_START_S),
            "anchor": "first_frame",
            "frames_analysed": len(csv_rows(d)),
        }
    ]
    assert out["coverage"]["frames_analysed"] == len(csv_rows(d)) > 0
    assert any("visible_001.mp4" in r.getMessage() for r in caplog.records)
    assert json.loads((d / "exports" / "visible_sample.json").read_text()) == out


@needs_ffmpeg
def test_runner_multi_segment_times_use_each_segment_start(
    tmp_path: Path, real: dict[str, Any], short_clip: Path, fixed_threshold: None
) -> None:
    d = experiment(tmp_path, real, [short_clip, short_clip], gap_s=50.0)
    out = run_analysis(d)
    assert out["status"] == "ok", out
    rows = csv_rows(d)
    first = {s: next(r for r in rows if int(r["segment"]) == s) for s in (0, 1)}
    # 10 fps: frames 0-2 (0.0-0.2 s) are skipped, so each segment's rows start at 0.3 s
    assert float(first[0]["t_s"]) == pytest.approx(T_START_S + 0.3, abs=1e-6)
    assert float(first[1]["t_s"]) == pytest.approx(T_START_S + 50.0 + 0.3, abs=1e-6)
    assert int(first[1]["frame"]) == 3
    assert first[1]["brightening"] == ""  # no previous analysed frame in its own segment
    assert out["coverage"]["t_first_s"] == pytest.approx(T_START_S + 0.3)
    assert out["coverage"]["gaps_over_300ms"] == 1  # the 50 s between the segments
    assert out["missing"] == []
    assert [(g["index"], g["file"]) for g in out["segments"]] == [
        (0, "visible.mp4"),
        (1, "visible_001.mp4"),
    ]
    assert [g["t_start_s"] for g in out["segments"]] == pytest.approx([T_START_S, T_START_S + 50])
    for g in out["segments"]:
        assert g["frames_analysed"] == sum(int(r["segment"]) == g["index"] for r in rows) > 0
    assert out["files"] == [
        "visible_sample.csv", "visible_sample_closeup.mp4", "visible_sample_closeup_001.mp4",
        "visible_sample_plot.png", "visible_sample.json",
    ]  # fmt: skip
    assert exported(d) == sorted(out["files"])


@needs_ffmpeg
def test_runner_fails_when_segments_are_out_of_time_order(
    tmp_path: Path, real: dict[str, Any], short_clip: Path, fixed_threshold: None
) -> None:
    """Events are merged on the assumption that the rows run forward in time."""
    d = experiment(tmp_path, real, [short_clip, short_clip], gap_s=-50.0)
    out = run_analysis(d)
    assert out["status"] == "failed"
    assert "time order" in out["reason"]
    assert exported(d) == ["visible_sample.json"]


def _drop_first_frame_anchor(d: Path, index: int) -> None:
    """Rewrite visible.json as a recording from before 2026-09-30 wrote it: that segment has only
    the ffmpeg launch time (``started_host_ns``), not the arrival of its first frame."""
    path = d / "visible.json"
    doc = json.loads(path.read_text())
    del doc["segments"][index]["first_frame_host_ns"]
    path.write_text(json.dumps(doc))


@needs_ffmpeg
def test_runner_reports_how_each_segment_was_anchored(
    tmp_path: Path, real: dict[str, Any], short_clip: Path, fixed_threshold: None
) -> None:
    """A segment with only the ffmpeg launch time sits ~1 s early on the thermal axis (the launch
    precedes the first frame by the RTSP connect time); the summary says which anchor each used."""
    d = experiment(tmp_path, real, [short_clip, short_clip], gap_s=50.0)
    _drop_first_frame_anchor(d, 1)  # the helper puts the launch 1 s before the first frame
    out = run_analysis(d, closeup=False)
    assert out["status"] == "ok", out
    anchors = [(g["index"], g["anchor"]) for g in out["segments"]]
    assert anchors == [(0, "first_frame"), (1, "launch")]
    assert [g["t_start_s"] for g in out["segments"]] == pytest.approx(
        [T_START_S, T_START_S + 50.0 - 1.0]
    )
    assert json.loads((d / "exports" / "visible_sample.json").read_text()) == out
