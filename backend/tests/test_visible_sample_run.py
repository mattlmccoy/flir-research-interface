"""The visible-sample runner on clips: the files it writes and what it measures.

The helpers and clip kinds (synthetic and real crops) are described in
tests/visible_sample_helpers.py.
"""

from __future__ import annotations

import json
import subprocess
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
from flir_research_interface.playback.visible_timing import FRAME0_SKIP_S
from tests import visible_sample_helpers as vh
from tests.visible_sample_helpers import (
    CSV_COLUMNS,
    FFMPEG,
    FIXTURES,
    T_START_S,
    VIS_H,
    VIS_W,
    csv_rows,
    experiment,
    exported,
    lossless_clip,
    needs_ffmpeg,
    packet_times,
    run_analysis,
    synthetic_clip,
    video_size,
)

# The shared fixtures, bound here so that pytest finds them in this module (importing them by name
# would make ruff report F811 wherever a test takes one as an argument).
real, clip, short_clip, fixed_threshold = vh.real, vh.clip, vh.short_clip, vh.fixed_threshold


# -- the analysis on clips ---------------------------------------------------------------------


@needs_ffmpeg
def test_runner_ok_synthetic_clip(
    tmp_path: Path, real: dict[str, Any], clip: Path, fixed_threshold: None
) -> None:
    """synthetic: decode/timing plumbing only, not detection truth."""
    d = experiment(tmp_path, real, [clip])
    out = run_analysis(d)
    assert out["status"] == "ok" and out["reason"] is None, out
    pts = packet_times(clip)
    analysed = [p for p in pts if p >= FRAME0_SKIP_S]
    rows = csv_rows(d)
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
    assert video_size(closeup) == (3 * side, 3 * side)
    assert out["files"] == [
        "visible_sample.csv", "visible_sample_closeup.mp4", "visible_sample_plot.png",
        "visible_sample.json",
    ]  # fmt: skip
    assert exported(d) == sorted(out["files"])
    assert json.loads((d / "exports" / "visible_sample.json").read_text()) == out


@needs_ffmpeg
def test_runner_reports_the_alignment_used(
    tmp_path: Path, real: dict[str, Any], short_clip: Path, fixed_threshold: None
) -> None:
    saved = real["visible_alignment"]
    d = experiment(tmp_path, real, [short_clip])
    out = run_analysis(d, closeup=False)
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
    d = experiment(tmp_path, real, [short_clip], alignment={"H": real["visible_alignment"]["H"]})
    out = run_analysis(d, closeup=False)
    assert out["status"] == "ok"
    assert out["alignment"] == {"saved_utc": None, "rmsPx": None, "n_pairs": None}


@needs_ffmpeg
def test_runner_without_closeup_or_bed(
    tmp_path: Path, real: dict[str, Any], clip: Path, fixed_threshold: None
) -> None:
    rois = [r for r in real["rois"] if r["name"] != "powder"]
    d = experiment(tmp_path, real, [clip], rois=rois)
    out = run_analysis(d, closeup=False)
    assert out["status"] == "ok" and out["bed_roi"] is None
    assert all(r["bed_clipped_frac"] == "" for r in csv_rows(d))
    assert out["files"] == ["visible_sample.csv", "visible_sample_plot.png", "visible_sample.json"]
    assert exported(d) == sorted(out["files"])


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
    clip = lossless_clip(tmp_path / "real.mp4", planes)
    d = experiment(tmp_path, real, [clip])
    out = run_analysis(d)
    assert out["status"] == "ok", out
    assert out["threshold"] == 178  # Otsu over the 24 frames, as the fixture pins
    rows = csv_rows(d)
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
    clip = lossless_clip(tmp_path / "pattern.mp4", planes)
    d = experiment(tmp_path, real, [clip], rois=rois)
    out = run_analysis(d, closeup=False)
    assert out["status"] == "ok" and out["bed_roi"] == {"id": 7, "name": "bed"}
    pts = ir_to_visible_points(roi_outline_ir(bed), real["visible_alignment"]["H"])
    placed = region_mask(pts, 0)
    assert placed is not None
    mask, (bx, by, bw, bh) = placed
    assert bx > out["bbox"]["x0"]  # the bed's corner is not the decoded crop's corner
    rows = csv_rows(d)
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
    long = synthetic_clip(tmp_path / "long.mp4", real, 8.0, 6.0)
    d = experiment(tmp_path, real, [long])
    out = run_analysis(d, closeup=False)
    assert out["status"] == "ok" and out["coverage"]["frames_analysed"] == 77
    assert seen == [51 * int(_sample_mask(real).sum())]


@needs_ffmpeg
def test_runner_real_glow_makes_one_event_with_bbox(
    tmp_path: Path, real: dict[str, Any], captured: dict[int, np.ndarray]
) -> None:
    """Frames 6141 (x6), 6142 (the flash at 627.77 s) and 6143 (x3) of the real run."""
    order = [6141] * 9 + [6142] + [6143] * 3
    clip = lossless_clip(tmp_path / "glow.mp4", [_paste(real, captured[f]) for f in order])
    d = experiment(tmp_path, real, [clip])
    out = run_analysis(d, closeup=False)
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
    assert cmd[cmd.index("-fps_mode") + 1] == "passthrough"
    assert cmd[cmd.index("-crf") + 1] == "20"
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
