"""The visible-sample runner: ffprobe/ffmpeg I/O, segments on the thermal axis, files and statuses.

Experiments are built with ``Recorder`` at 640x480 with the real run's ``visible_alignment`` and
``rois`` (tests/fixtures/README.md). Two kinds of clip stand in for ``visible.mp4``:

* synthetic (a white frame, a dark square from 1.0 s on): decode/timing plumbing only, not
  detection truth;
* real crops (the luma crops of the fixture, pasted into a white frame and encoded lossless, so
  the decoded values equal the captured ones): the crop offsets, threshold, area and brightening
  are checked against the values the fixture pins.
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from flir_research_interface.analysis import visible_sample_run as vsr
from flir_research_interface.analysis.visible_sample import (
    ir_to_visible_points,
    pick_rois,
    region_mask,
    roi_outline_ir,
)
from flir_research_interface.analysis.visible_sample_run import analyse_visible_sample
from flir_research_interface.camera.base import Frame
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.playback.visible_timing import FRAME0_SKIP_S
from flir_research_interface.recording.recorder import Recorder
from flir_research_interface.visible.recorder import FFMPEG_CANDIDATES
from flir_research_interface.visible.rtsp import find_ffprobe

FIXTURES = Path(__file__).parent / "fixtures"
FFMPEG = find_ffprobe(FFMPEG_CANDIDATES)
FFPROBE = find_ffprobe()
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None or FFPROBE is None, reason="ffmpeg not installed")

HOST_T0_NS = 5_000_000_000  # thermal frame 0 arrives at this host time
T_START_S = 25.996  # where the first visible segment starts on the thermal axis (the real run's)
VIS_W, VIS_H = 1280, 960
CSV_COLUMNS = [
    "t_s",
    "segment",
    "frame",
    "keyframe",
    "sample_dark_px",
    "sample_mean_luma",
    "bed_clipped_frac",
    "brightening",
]


@pytest.fixture(scope="module")
def real() -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(
        (FIXTURES / "visible_sample_20261020_144402.json").read_text()
    )
    return doc


def _sample_box(real: dict[str, Any]) -> tuple[int, int, int, int]:
    """The mapped sample ROI's bounding box in visible pixels: x0, y0, w, h."""
    sample, _ = pick_rois(real["rois"])
    assert sample is not None
    pts = ir_to_visible_points(roi_outline_ir(sample), real["visible_alignment"]["H"])
    x0, y0 = np.floor(pts.min(axis=0)).astype(int)
    x1, y1 = np.ceil(pts.max(axis=0)).astype(int)
    return int(x0), int(y0), int(x1 - x0), int(y1 - y0)


def _synthetic_clip(path: Path, real: dict[str, Any], seconds: float, dark_from_s: float) -> Path:
    """White 1280x960 at 10 fps with a dark square over the sample from ``dark_from_s`` on."""
    assert FFMPEG is not None
    x, y, w, h = _sample_box(real)
    subprocess.run(
        [
            FFMPEG, "-v", "error", "-y",
            "-f", "lavfi", "-i", "color=white:s=1280x960:r=10", "-t", str(seconds),
            "-vf", f"drawbox=x={x}:y={y}:w={w}:h={h}:color=black:t=fill:"
                   f"enable='gte(t,{dark_from_s})'",
            "-c:v", "libx264", "-profile:v", "baseline", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-x264-params", "keyint=5", str(path),
        ],
        check=True,
    )  # fmt: skip
    return path


def _lossless_clip(path: Path, planes: list[np.ndarray]) -> Path:
    """Encode full-frame luma planes (grey chroma) lossless, 10 fps, so decoding returns them."""
    assert FFMPEG is not None
    grey = bytes([128]) * (VIS_W * VIS_H // 2)
    raw = b"".join(p.tobytes() + grey for p in planes)
    subprocess.run(
        [
            FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "yuv420p",
            "-s", f"{VIS_W}x{VIS_H}", "-r", "10", "-i", "-",
            "-c:v", "libx264", "-qp", "0", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            str(path),
        ],
        input=raw, check=True,
    )  # fmt: skip
    return path


@pytest.fixture(scope="module")
def clip(tmp_path_factory: pytest.TempPathFactory, real: dict[str, Any]) -> Path:
    """synthetic: 3 s, dark square from 1.0 s."""
    return _synthetic_clip(tmp_path_factory.mktemp("clip") / "c.mp4", real, 3.0, 1.0)


@pytest.fixture(scope="module")
def short_clip(tmp_path_factory: pytest.TempPathFactory, real: dict[str, Any]) -> Path:
    """synthetic: 1.5 s, dark square from 0.5 s."""
    return _synthetic_clip(tmp_path_factory.mktemp("short") / "s.mp4", real, 1.5, 0.5)


@pytest.fixture
def fixed_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """The synthetic scene has two luma levels, where Otsu's tie goes to the lower one and so
    calls the dark square not dark. These tests are about plumbing, so fix the threshold."""
    monkeypatch.setattr(vsr, "otsu_threshold", lambda values: 128)


def _experiment(
    root: Path,
    real: dict[str, Any],
    clips: list[Path] | None = None,
    *,
    gap_s: float = 50.0,
    alignment: dict[str, Any] | bool = True,
    rois: list[dict[str, Any]] | None = None,
) -> Path:
    """A 640x480 recording with the real alignment and ROIs and ``clips`` as visible segments.

    Segment i starts ``i * gap_s`` after the first, which starts at T_START_S.
    """
    rec = Recorder(None, experiments_root=root, chunk_frames=4)
    extra: dict[str, Any] = {"rois": real["rois"] if rois is None else rois}
    if alignment is True:
        extra["visible_alignment"] = real["visible_alignment"]
    elif alignment:
        extra["visible_alignment"] = alignment
    d = rec.start(
        name="vis",
        metadata={},
        camera_info={"backend": "simulated", "ir_format": "TemperatureLinear10mK", "model": "Sim"},
        extra=extra,
    )
    for i in range(3):
        rec.submit(
            Frame(
                frame_id=1 + i,
                device_timestamp_ns=1_000_000_000 + i * 100_000_000,
                host_timestamp_ns=HOST_T0_NS + i * 100_000_000,
                pixel_format="Mono16",
                ir_format="TemperatureLinear10mK",
                counts=np.full((480, 640), 29815, dtype=np.uint16),
                incomplete=False,
            )
        )
    rec.stop()
    segments = []
    for i, src in enumerate(clips or []):
        name = "visible.mp4" if i == 0 else f"visible_{i:03d}.mp4"
        shutil.copy(src, d / name)
        started = HOST_T0_NS + round((T_START_S + i * gap_s) * 1e9)
        segments.append(
            {
                "index": i,
                "file": name,
                "started_host_ns": started - 1_000_000_000,
                "first_frame_host_ns": started,
                "duration_s": 3.0,
                "offset_s": i * gap_s,
            }
        )
    if segments:
        side = {"file": "visible.mp4", "started_host_ns": segments[0]["started_host_ns"]}
        (d / "visible.json").write_text(json.dumps({**side, "segments": segments}))
    return d


def _run(d: Path, **kw: Any) -> dict[str, Any]:
    return analyse_visible_sample(ExperimentReader(d), **kw)


def _exports(d: Path) -> list[str]:
    folder = d / "exports"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def _rows(d: Path) -> list[dict[str, str]]:
    with (d / "exports" / "visible_sample.csv").open(newline="") as fh:
        return list(csv.DictReader(fh))


def _packet_times(path: Path) -> list[float]:
    assert FFPROBE is not None
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return [float(x) for x in out.split()]


def _video_size(path: Path) -> tuple[int, int]:
    assert FFPROBE is not None
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    w, h = out.strip().split(",")
    return int(w), int(h)


# -- skips: the video cannot be analysed, and the JSON says why --------------------------------


def _assert_skipped(out: dict[str, Any], d: Path, reason: str) -> None:
    assert out["status"] == "skipped"
    assert out["reason"] == reason
    assert out["files"] == ["visible_sample.json"]
    assert "events" not in out and "coverage" not in out  # never an empty "no events"
    assert _exports(d) == ["visible_sample.json"]
    assert json.loads((d / "exports" / "visible_sample.json").read_text()) == out


def test_runner_skips_without_visible(tmp_path: Path, real: dict[str, Any]) -> None:
    d = _experiment(tmp_path, real)
    _assert_skipped(_run(d), d, "no visible video")


@pytest.mark.parametrize("n_listed", [1, 2])
def test_runner_skips_when_every_listed_segment_is_missing(
    tmp_path: Path, real: dict[str, Any], n_listed: int
) -> None:
    dummy = tmp_path / "dummy.mp4"
    dummy.write_bytes(b"not a video")
    d = _experiment(tmp_path, real, [dummy] * n_listed)
    for path in d.glob("visible*.mp4"):
        path.unlink()
    _assert_skipped(_run(d), d, "no visible video")


def test_runner_skips_without_alignment(tmp_path: Path, real: dict[str, Any]) -> None:
    dummy = tmp_path / "dummy.mp4"
    dummy.write_bytes(b"not a video")
    d = _experiment(tmp_path, real, [dummy], alignment=False)
    _assert_skipped(_run(d), d, "no visible alignment")


def test_runner_skips_without_sample_roi(tmp_path: Path, real: dict[str, Any]) -> None:
    dummy = tmp_path / "dummy.mp4"
    dummy.write_bytes(b"not a video")
    rois = [r for r in real["rois"] if "sample" not in r["name"]]
    d = _experiment(tmp_path, real, [dummy], rois=rois)
    _assert_skipped(_run(d), d, "no sample ROI (name containing 'sample')")


@needs_ffmpeg
def test_runner_skips_when_roi_outside_frame(
    tmp_path: Path, real: dict[str, Any], clip: Path
) -> None:
    far = {"id": 1, "kind": "polygon", "name": "sample",
           "points": [[-900, -900], [-850, -900], [-850, -850], [-900, -850]]}  # fmt: skip
    d = _experiment(tmp_path, real, [clip], rois=[far])
    _assert_skipped(_run(d), d, "sample ROI maps outside the visible frame")


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
    d = _experiment(tmp_path, real, [clip], rois=[sample], alignment={"H": h_matrix})
    _assert_skipped(_run(d), d, "visible alignment is invalid")


# -- the analysis on clips ---------------------------------------------------------------------


@needs_ffmpeg
def test_runner_ok_synthetic_clip(
    tmp_path: Path, real: dict[str, Any], clip: Path, fixed_threshold: None
) -> None:
    """synthetic: decode/timing plumbing only, not detection truth."""
    d = _experiment(tmp_path, real, [clip])
    out = _run(d)
    assert out["status"] == "ok" and out["reason"] is None, out
    pts = _packet_times(clip)
    analysed = [p for p in pts if p >= FRAME0_SKIP_S]
    rows = _rows(d)
    assert len(rows) == len(analysed) == len(pts) - sum(p < FRAME0_SKIP_S for p in pts)
    assert float(rows[0]["t_s"]) == pytest.approx(T_START_S + analysed[0], abs=1e-6)
    assert list(rows[0]) == CSV_COLUMNS
    seen = [(float(r["t_s"]) - T_START_S, int(r["sample_dark_px"])) for r in rows]
    assert all(n == 0 for s, n in seen if s < 0.95)
    assert all(n > 0 for s, n in seen if s > 1.05)
    first_dark = next(s for s, n in seen if n > 0)
    assert first_dark == pytest.approx(1.0, abs=0.1)
    # keyframes (every 5th frame here) and each segment's first row carry no brightening
    for r in rows[1:]:
        assert (r["brightening"] == "") == (r["keyframe"] == "1")
    assert rows[0]["brightening"] == ""
    assert out["coverage"]["frames_analysed"] == len(rows)
    assert out["threshold"] == 128
    assert out["sample_roi"] == {"id": 101, "name": "freehand_sample"}
    assert out["bed_roi"] == {"id": 94, "name": "powder"}
    closeup = d / "exports" / "visible_sample_closeup.mp4"
    side = max(out["bbox"]["w"], out["bbox"]["h"])
    assert _video_size(closeup) == (3 * side, 3 * side)
    assert out["files"] == [
        "visible_sample.csv", "visible_sample_closeup.mp4", "visible_sample_plot.png",
        "visible_sample.json",
    ]  # fmt: skip
    assert _exports(d) == sorted(out["files"])
    assert json.loads((d / "exports" / "visible_sample.json").read_text()) == out


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
    d = _experiment(tmp_path, real, [short_clip, short_clip])
    (d / "visible_001.mp4").unlink()
    with caplog.at_level("WARNING", logger=vsr.logger.name):
        out = _run(d, closeup=False)
    assert out["status"] == "ok", out
    assert out["missing"] == ["visible_001.mp4"]
    assert out["segments"] == [
        {
            "index": 0,
            "file": "visible.mp4",
            "t_start_s": pytest.approx(T_START_S),
            "frames_analysed": len(_rows(d)),
        }
    ]
    assert out["coverage"]["frames_analysed"] == len(_rows(d)) > 0
    assert any("visible_001.mp4" in r.getMessage() for r in caplog.records)
    assert json.loads((d / "exports" / "visible_sample.json").read_text()) == out


@needs_ffmpeg
def test_runner_reports_the_alignment_used(
    tmp_path: Path, real: dict[str, Any], short_clip: Path, fixed_threshold: None
) -> None:
    saved = real["visible_alignment"]
    d = _experiment(tmp_path, real, [short_clip])
    out = _run(d, closeup=False)
    assert out["alignment"] == {
        "saved_utc": saved["saved_utc"],
        "rmsPx": saved["rmsPx"],
        "n_pairs": len(saved["pairs"]),
    }
    assert out["alignment"]["n_pairs"] == 10
    assert out["alignment"]["saved_utc"] == "2026-09-02T18:19:01.184354+00:00"
    assert out["alignment"]["rmsPx"] == pytest.approx(2.888, abs=1e-3)


@needs_ffmpeg
def test_runner_alignment_fields_that_are_absent_are_none(
    tmp_path: Path, real: dict[str, Any], short_clip: Path, fixed_threshold: None
) -> None:
    d = _experiment(tmp_path, real, [short_clip], alignment={"H": real["visible_alignment"]["H"]})
    out = _run(d, closeup=False)
    assert out["status"] == "ok"
    assert out["alignment"] == {"saved_utc": None, "rmsPx": None, "n_pairs": None}


@needs_ffmpeg
def test_runner_without_closeup_or_bed(
    tmp_path: Path, real: dict[str, Any], clip: Path, fixed_threshold: None
) -> None:
    rois = [r for r in real["rois"] if r["name"] != "powder"]
    d = _experiment(tmp_path, real, [clip], rois=rois)
    out = _run(d, closeup=False)
    assert out["status"] == "ok" and out["bed_roi"] is None
    assert all(r["bed_clipped_frac"] == "" for r in _rows(d))
    assert out["files"] == ["visible_sample.csv", "visible_sample_plot.png", "visible_sample.json"]
    assert _exports(d) == sorted(out["files"])


@needs_ffmpeg
def test_runner_multi_segment_times_use_each_segment_start(
    tmp_path: Path, real: dict[str, Any], short_clip: Path, fixed_threshold: None
) -> None:
    d = _experiment(tmp_path, real, [short_clip, short_clip], gap_s=50.0)
    out = _run(d)
    assert out["status"] == "ok", out
    rows = _rows(d)
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
    assert _exports(d) == sorted(out["files"])


@needs_ffmpeg
def test_runner_fails_when_segments_are_out_of_time_order(
    tmp_path: Path, real: dict[str, Any], short_clip: Path, fixed_threshold: None
) -> None:
    """Events are merged on the assumption that the rows run forward in time."""
    d = _experiment(tmp_path, real, [short_clip, short_clip], gap_s=-50.0)
    out = _run(d)
    assert out["status"] == "failed"
    assert "time order" in out["reason"]
    assert _exports(d) == ["visible_sample.json"]


@needs_ffmpeg
def test_runner_writes_atomically_and_overwrites(
    tmp_path: Path,
    real: dict[str, Any],
    short_clip: Path,
    fixed_threshold: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    d = _experiment(tmp_path, real, [short_clip])
    exports = d / "exports"
    csv_path, mp4_path, png_path = (
        exports / "visible_sample.csv",
        exports / "visible_sample_closeup.mp4",
        exports / "visible_sample_plot.png",
    )
    first = _run(d)
    assert first["status"] == "ok"
    good_csv = csv_path.read_text()
    csv_path.write_text("stale")
    mp4_path.write_bytes(b"stale")
    assert _run(d)["status"] == "ok"
    assert csv_path.read_text() == good_csv and mp4_path.stat().st_size > 5  # replaced
    assert not list(exports.glob("*.part"))
    # an explicit ffmpeg that is not an executable file: skipped, and nothing stale is left
    png_path.write_bytes(b"stale")
    (exports / "visible_sample.csv.part").write_text("half")
    out = _run(d, ffmpeg="/nonexistent")
    assert out["status"] == "skipped" and out["reason"] == "ffmpeg not found"
    assert _exports(d) == ["visible_sample.json"]
    # a decode that dies mid-stream: failed, with no half-written or older results left
    assert _run(d)["status"] == "ok"
    png_path.write_bytes(b"stale")
    real_decode = vsr._decode_luma

    def dies_mid_stream(*args: Any, **kw: Any) -> Iterator[Any]:
        for i, frame in enumerate(real_decode(*args, **kw)):
            if i == 5:
                raise RuntimeError("decoder died")
            yield frame

    monkeypatch.setattr(vsr, "_decode_luma", dies_mid_stream)
    out = _run(d)
    assert out["status"] == "failed" and out["reason"] == "RuntimeError: decoder died"
    assert _exports(d) == ["visible_sample.json"]
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
    d = _experiment(tmp_path, real, [short_clip])
    out = _run(d)
    assert out["status"] == "failed" and out["reason"] == "RuntimeError: encoder died"
    assert _exports(d) == ["visible_sample.json"]  # the CSV that was ready is not kept either


@needs_ffmpeg
def test_runner_frame_count_mismatch_fails(
    tmp_path: Path,
    real: dict[str, Any],
    short_clip: Path,
    fixed_threshold: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_probe = vsr._probe

    def one_extra_packet(*args: Any, **kw: Any) -> Any:
        probe = real_probe(*args, **kw)
        return type(probe)(
            width=probe.width,
            height=probe.height,
            pts_s=np.append(probe.pts_s, probe.pts_s[-1] + 0.1),
            keyframe=np.append(probe.keyframe, False),
        )

    monkeypatch.setattr(vsr, "_probe", one_extra_packet)
    d = _experiment(tmp_path, real, [short_clip])
    out = _run(d)
    assert out["status"] == "failed"
    assert "frame count" in out["reason"]
    assert _exports(d) == ["visible_sample.json"]


# -- real crops: the captured luma through the whole runner ------------------------------------


@pytest.fixture(scope="module")
def captured() -> dict[int, np.ndarray]:
    """The fixture's luma crops by frame index."""
    npz = np.load(FIXTURES / "visible_sample_20261020_144402.npz")
    return {int(f): npz["crops"][i] for i, f in enumerate(npz["crop_frames"].tolist())}


def _sample_region(real: dict[str, Any]) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """The analysis region of the real run: its mask and its box (x0, y0, w, h)."""
    sample, _ = pick_rois(real["rois"])
    assert sample is not None
    pts = ir_to_visible_points(roi_outline_ir(sample), real["visible_alignment"]["H"])
    out = region_mask(pts, 30)
    assert out is not None
    return out


def _sample_mask(real: dict[str, Any]) -> np.ndarray:
    return _sample_region(real)[0]


def _assert_closeup_is_the_stretched_crop(
    d: Path, out: dict[str, Any], plane: np.ndarray, lo: float
) -> None:
    """The first close-up frame, shrunk back 3x, is the source crop with luma lo..250 -> 0..255
    (up to what the encoder and the resampling change)."""
    box = out["bbox"]
    x, y, side = vsr._closeup_box((box["x0"], box["y0"], box["w"], box["h"]), (VIS_W, VIS_H))
    path = d / "exports" / "visible_sample_closeup.mp4"
    assert FFMPEG is not None
    raw = subprocess.run(
        [FFMPEG, "-v", "fatal", "-i", str(path), "-vf", "extractplanes=y",
         "-fps_mode", "passthrough", "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    first = np.frombuffer(raw, np.uint8).reshape(-1, 3 * side, 3 * side)[0].astype(float)
    shrunk = first.reshape(side, 3, side, 3).mean(axis=(1, 3))
    source = plane[y : y + side, x : x + side].astype(float)
    expected = np.clip((source - lo) * 255 / (250 - lo), 0, 255)
    assert np.abs(shrunk - expected).mean() < 2.0
    assert expected.min() < 60 and expected.max() == 255  # the stretch is not a no-op


def _paste(real: dict[str, Any], crop: np.ndarray) -> np.ndarray:
    """A white frame with ``crop`` where the analysis region's bounding box is."""
    x0, y0, w, h = _sample_region(real)[1]
    assert crop.shape == (h, w)
    plane = np.full((VIS_H, VIS_W), 255, dtype=np.uint8)
    plane[y0 : y0 + h, x0 : x0 + w] = crop
    return plane


@needs_ffmpeg
def test_runner_real_crops_threshold_area_and_brightening(
    tmp_path: Path, real: dict[str, Any], captured: dict[int, np.ndarray]
) -> None:
    """Frames 0-2 repeat frame 3 (skipped); frames 3-26 are the fixture's first 5 s."""
    fixture = np.load(FIXTURES / "visible_sample_20261020_144402.npz")
    planes = [_paste(real, captured[max(i, 3)]) for i in range(27)]
    clip = _lossless_clip(tmp_path / "real.mp4", planes)
    d = _experiment(tmp_path, real, [clip])
    out = _run(d)
    assert out["status"] == "ok", out
    assert out["threshold"] == 178  # Otsu over the 24 frames, as the fixture pins
    rows = _rows(d)
    assert [int(r["frame"]) for r in rows] == list(range(3, 27))
    dark = [int(r["sample_dark_px"]) for r in rows]
    assert np.mean(dark) == pytest.approx(1095, rel=0.01)
    assert dark[0] == pytest.approx(1100, rel=0.01)
    # brightening is the fixture's series (the runner and the capture script share the definition)
    series = fixture["brightening"]
    for r in rows[1:]:
        if r["keyframe"] != "1":
            assert float(r["brightening"]) == pytest.approx(series[int(r["frame"])])
    # the bed is read in full-frame coordinates: compare with an independent whole-frame count
    _, bed = pick_rois(real["rois"])
    assert bed is not None
    bed_pts = ir_to_visible_points(roi_outline_ir(bed), real["visible_alignment"]["H"])
    bed_mask = region_mask(bed_pts, 0)
    assert bed_mask is not None
    mask, (bx, by, bw, bh) = bed_mask
    frame4 = planes[4][by : by + bh, bx : bx + bw]
    assert float(rows[1]["bed_clipped_frac"]) == pytest.approx(np.mean(frame4[mask] == 255))
    assert 0.0 < float(rows[1]["bed_clipped_frac"]) < 1.0
    # the close-up's black level is the 1st percentile of the dark pixels' luma over the run
    region_px = [captured[f][_sample_mask(real)] for f in range(3, 27)]
    dark_px = np.concatenate([px[px < 178] for px in region_px])
    lo = round(min(float(np.percentile(dark_px, 1)), 249.0), 2)
    assert out["stretch"] == {"lo": lo, "hi": 250}
    _assert_closeup_is_the_stretched_crop(d, out, planes[3], lo)


@needs_ffmpeg
def test_runner_reads_a_bed_beside_the_sample_at_its_own_offset(
    tmp_path: Path, real: dict[str, Any]
) -> None:
    """The bed need not enclose the sample (in the real run it does): each mask goes into the
    decoded crop at its own corner. The frames are a pattern clipped to 255 in about a quarter of
    their pixels, so a mask in the wrong place gives another fraction."""
    bed = {"id": 7, "kind": "rect", "name": "bed", "x0": 230, "y0": 215, "x1": 290, "y1": 275}
    rois = [r for r in real["rois"] if r["name"] == "freehand_sample"] + [bed]
    yy, xx = np.mgrid[0:VIS_H, 0:VIS_W]
    planes = []
    for k in range(8):
        level = ((xx // 4) * 7 + (yy // 4) * 13 + 17 * k) % 256
        planes.append(np.where(level > 192, 255, level).astype(np.uint8))
    clip = _lossless_clip(tmp_path / "pattern.mp4", planes)
    d = _experiment(tmp_path, real, [clip], rois=rois)
    out = _run(d, closeup=False)
    assert out["status"] == "ok" and out["bed_roi"] == {"id": 7, "name": "bed"}
    pts = ir_to_visible_points(roi_outline_ir(bed), real["visible_alignment"]["H"])
    placed = region_mask(pts, 0)
    assert placed is not None
    mask, (bx, by, bw, bh) = placed
    assert bx > out["bbox"]["x0"]  # the bed's corner is not the decoded crop's corner
    rows = _rows(d)
    assert len(rows) == 5
    for r in rows:
        window = planes[int(r["frame"])][by : by + bh, bx : bx + bw]
        expected = np.mean(window[mask] == 255)
        assert float(r["bed_clipped_frac"]) == pytest.approx(expected, abs=1e-6)  # CSV: 6 decimals


@needs_ffmpeg
def test_runner_threshold_comes_from_the_first_five_seconds(
    tmp_path: Path, real: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """synthetic: decode/timing plumbing only. 10 fps, frames 0-2 skipped: the analysed frames
    start at 0.3 s, so the 5 s window holds frames 3-53 of the 8 s clip."""
    seen: list[int] = []

    def record(values: np.ndarray) -> int:
        seen.append(values.size)
        return 128

    monkeypatch.setattr(vsr, "otsu_threshold", record)
    long = _synthetic_clip(tmp_path / "long.mp4", real, 8.0, 6.0)
    d = _experiment(tmp_path, real, [long])
    out = _run(d, closeup=False)
    assert out["status"] == "ok" and out["coverage"]["frames_analysed"] == 77
    assert seen == [51 * int(_sample_mask(real).sum())]


@needs_ffmpeg
def test_runner_real_glow_makes_one_event_with_bbox(
    tmp_path: Path, real: dict[str, Any], captured: dict[int, np.ndarray]
) -> None:
    """Frames 6141 (x6), 6142 (the flash at 627.77 s) and 6143 (x3) of the real run."""
    order = [6141] * 9 + [6142] + [6143] * 3
    clip = _lossless_clip(tmp_path / "glow.mp4", [_paste(real, captured[f]) for f in order])
    d = _experiment(tmp_path, real, [clip])
    out = _run(d, closeup=False)
    assert out["status"] == "ok", out
    assert out["flash_threshold"] == 15.0
    assert len(out["events"]) == 1
    event = out["events"][0]
    assert event["peak_frame"] == 9  # the frame index in the file, not in the analysed list
    assert event["segment"] == 0
    assert event["peak_brightening"] == pytest.approx(97, abs=1)
    assert event["n_frames"] == 2  # the glow (+97) and the frame after it (+27)
    assert event["t_peak_s"] == pytest.approx(T_START_S + 0.9)
    assert event["bbox"] == _brightest_blocks(real, captured[6141], captured[6142])


def _brightest_blocks(
    real: dict[str, Any], before: np.ndarray, after: np.ndarray
) -> dict[str, int]:
    """The event box by the rule, worked out from the crops alone: the 16 px blocks (from the
    region's corner) whose mean luma change over the region is at least half the largest."""
    sample, _ = pick_rois(real["rois"])
    assert sample is not None
    pts = ir_to_visible_points(roi_outline_ir(sample), real["visible_alignment"]["H"])
    region = region_mask(pts, 30)
    assert region is not None
    mask, (x0, y0, w, h) = region
    change = after.astype(int) - before.astype(int)
    means = {}
    for by in range(0, h, 16):
        for bx in range(0, w, 16):
            inside = mask[by : by + 16, bx : bx + 16]
            if inside.any():
                means[(bx, by)] = change[by : by + 16, bx : bx + 16][inside].mean()
    top = max(means.values())
    hit = [corner for corner, m in means.items() if m >= top / 2]
    left, upper = min(bx for bx, _ in hit), min(by for _, by in hit)
    right, lower = min(max(bx for bx, _ in hit) + 16, w), min(max(by for _, by in hit) + 16, h)
    return {"x0": x0 + left, "y0": y0 + upper, "w": right - left, "h": lower - upper}


# -- pure helpers ------------------------------------------------------------------------------


def test_hist_percentile_matches_numpy() -> None:
    rng = np.random.default_rng(7)
    values = rng.integers(40, 180, size=5000).astype(np.uint8)
    hist = np.bincount(values, minlength=256)
    for q in (0.0, 1.0, 50.0, 99.0, 100.0):
        assert vsr._hist_percentile(hist, q) == pytest.approx(float(np.percentile(values, q)))
    assert vsr._hist_percentile(np.zeros(256, dtype=np.int64), 1.0) is None


def test_stretch_lo_is_the_first_percentile_and_stays_below_hi() -> None:
    hist = np.zeros(256, dtype=np.int64)
    assert vsr._stretch_lo(hist) == 0.0  # no dark pixel anywhere: stretch from black
    hist[110] = 1000
    hist[60] = 2
    assert vsr._stretch_lo(hist) == 110.0  # the 1st percentile of 1002 values skips the two 60s
    hist = np.zeros(256, dtype=np.int64)
    hist[254] = 10
    assert vsr._stretch_lo(hist) == 249.0  # a stretch to 250 needs LO below 250


def test_flash_bbox_is_the_blocks_near_the_largest_change() -> None:
    window = (320, 400, 40, 36)  # x0, y0, w, h of the sample region (3 x 3 blocks of 16 px)
    counts = np.full((3, 3), 256)
    counts[:, 2] = 128  # the last block column holds 8 px of region per row
    counts[2, :] = 64  # the last block row holds 4 px of region per column
    sums = np.zeros((3, 3), dtype=np.int32)
    sums[2, 0] = 64 * 90  # mean change +90: the largest
    sums[2, 1] = 64 * 50  # +50: at least half of it, so included
    sums[0, 2] = 128 * 20  # +20: less than half, left out
    box = vsr._flash_bbox(sums, counts, window)
    assert box == {"x0": 320, "y0": 432, "w": 32, "h": 4}  # clipped to the region's 36 px height
    assert vsr._flash_bbox(np.zeros((3, 3), dtype=np.int32), counts, window) is None
    assert vsr._flash_bbox(-sums, counts, window) is None  # only brightening counts


def test_closeup_box_is_square_even_and_inside_the_frame() -> None:
    assert vsr._closeup_box((347, 405, 126, 124), (1280, 960)) == (346, 404, 126)
    x, y, side = vsr._closeup_box((0, 0, 40, 30), (1280, 960))  # in the corner
    assert (x, y, side) == (0, 0, 40)
    x, y, side = vsr._closeup_box((1240, 930, 40, 30), (1280, 960))  # at the far corner
    assert (x, y, side) == (1240, 920, 40)
    x, y, side = vsr._closeup_box((1, 1, 1279, 959), (1280, 960))  # larger than the frame
    assert side == 960 and x % 2 == 0 and y == 0


def test_closeup_command_stretches_luma_and_scales_by_three() -> None:
    cmd = vsr._closeup_command("ffmpeg", Path("in.mp4"), Path("out.part"), (320, 404, 126), 87.5)
    vf = cmd[cmd.index("-vf") + 1]
    assert vf == (
        "select='gte(t,0.25)',crop=126:126:320:404,"
        "lutyuv=y='clip((val-87.5)*255/(250-87.5),0,255)',"
        "scale=378:378:flags=lanczos"
    )
    assert cmd[cmd.index("-fps_mode") + 1] == "vfr"
    assert cmd[cmd.index("-crf") + 1] == "20"
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"

