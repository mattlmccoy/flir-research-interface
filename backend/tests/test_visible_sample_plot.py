"""The visible-sample timeline plot (``exports/visible_sample_plot.png``) and the runner writing it.

The drawing tests are shape-only: the rows and the summary are built to the shape the runner
makes (``visible_sample_run._measure`` and ``_summary``), so they check where and in which colour
things are drawn, not what the analysis measures. The runner tests at the end run the real
analysis on a synthetic clip, so the plot is also fed real runner output.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from flir_research_interface.analysis import visible_sample_run as vsr
from flir_research_interface.analysis.run_summary import (
    MARGIN_L,
    MARGIN_R,
    PLOT_H,
    PLOT_W,
    roi_plot_png,
)
from flir_research_interface.analysis.visible_sample_plot import (
    BRIGHT_RGB,
    CEILING_RGB,
    DARK_RGB,
    EVENT_RGB,
    MAX_RGB,
    MEAN_RGB,
    RF_RGB,
    line_runs,
    median_by_run,
    panel_boxes,
    rolling_median,
    row_arrays,
    unit_label,
    visible_sample_plot_png,
)
from flir_research_interface.camera.base import Frame
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.recording.recorder import Recorder
from tests.visible_sample_helpers import (
    FIXTURES,
    experiment,
    exported,
    needs_ffmpeg,
    run_analysis,
    synthetic_clip,
)

N_FRAMES = 80  # thermal frames, 10 fps: 0 to 7.9 s
SAMPLE = {"id": 7, "kind": "rect", "name": "freehand_sample", "x0": 2, "y0": 2, "x1": 10, "y1": 10}
EVENT_T, EVENT_PEAK = 5.0, 97.2
ROW_T0, ROW_T1 = 0.3, 7.5  # the analysed frames cover this much of the thermal axis


def _thermal_run(
    root: Path,
    *,
    high_c: float | None = 250.0,
    ir_format: str = "TemperatureLinear10mK",
    control: bool = True,
) -> ExperimentReader:
    """A 16x16 recording, 10 fps, with the sample ROI warming 0.1 C per frame from 25 C (one hot
    pixel, so max and mean differ), and RF control samples every 5th frame when ``control``."""
    camera: dict[str, Any] = {"model": "Sim", "ir_format": ir_format}
    if high_c is not None:
        camera["active_case"] = {"index": 1, "low_c": -20.0, "high_c": high_c}
    rec = Recorder(None, experiments_root=root, chunk_frames=4, min_free_gb=0.0)
    d = rec.start(name="plot", metadata={}, camera_info=camera, extra={"rois": [SAMPLE]})
    for i in range(N_FRAMES):
        counts = np.full((16, 16), 29815 + 10 * i, dtype=np.uint16)
        counts[4, 4] += 200
        rec.submit(
            Frame(
                frame_id=1 + i,
                device_timestamp_ns=i * 100_000_000,
                host_timestamp_ns=i * 100_000_000,
                pixel_format="Mono16",
                ir_format=ir_format,
                counts=counts,
                incomplete=False,
            )
        )
        if control and i % 5 == 0:
            rec.note_event("control", {"forward_w": 20.0 + i, "measured_c": 25.0 + 0.1 * i})
    rec.stop()
    return ExperimentReader(d)


def _rows() -> list[dict[str, Any]]:
    """Rows as the runner holds them: 10 fps, a keyframe every 25th frame (no brightening there),
    none for the first analysed frame, and one bright frame at ``EVENT_T``."""
    rows = []
    for i, t in enumerate(np.arange(ROW_T0, ROW_T1 + 1e-9, 0.1)):
        key = i % 25 == 0
        flash = abs(t - EVENT_T) < 1e-6
        rows.append(
            {
                "t_s": round(float(t), 6),
                "segment": 0,
                "frame": 3 + i,
                "keyframe": key,
                "sample_dark_px": 100 + (i % 7) * 10,
                "sample_mean_luma": 40.0,
                "bed_clipped_frac": None,
                "brightening": None if key or i == 0 else (EVENT_PEAK if flash else 3.0 + i % 4),
            }
        )
    return rows


def _summary(events: bool = True) -> dict[str, Any]:
    event = {
        "t_start_s": EVENT_T - 0.1,
        "t_peak_s": EVENT_T,
        "t_end_s": EVENT_T + 0.1,
        "peak_brightening": EVENT_PEAK,
        "n_frames": 3,
        "peak_frame": 53,
        "segment": 0,
        "bbox": None,
    }
    return {
        "status": "ok",
        "sample_roi": {"id": SAMPLE["id"], "name": SAMPLE["name"]},
        "events": [event] if events else [],
    }


def _image(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).astype(int)


def _x_of(t: float) -> int:
    """The pixel column of time ``t``: the time axis runs from 0 to the end of the thermal run."""
    return round(MARGIN_L + (PLOT_W - MARGIN_L - MARGIN_R) * t / ((N_FRAMES - 1) / 10))


def _count(
    img: np.ndarray, rgb: tuple[int, ...], rows: tuple[int, int], cols: tuple[int, int]
) -> int:
    """Pixels of exactly ``rgb`` in the rows and columns (half-open)."""
    box = img[rows[0] : rows[1], cols[0] : cols[1]]
    return int((box == np.array(rgb)).all(axis=-1).sum())


def _panel_count(img: np.ndarray, rgb: tuple[int, ...], panel: int) -> int:
    top, bottom = panel_boxes()[panel]
    return _count(img, rgb, (top, bottom + 1), (MARGIN_L, PLOT_W - MARGIN_R))


# -- pure helpers -------------------------------------------------------------------------------


def test_rolling_median_is_centred_and_shrinks_at_the_ends() -> None:
    out = rolling_median(np.array([1.0, 2.0, 3.0, 4.0, 10.0]), window=3)
    assert out.tolist() == [1.5, 2.0, 3.0, 4.0, 7.0]


def test_rolling_median_default_is_31_frames_and_drops_a_spike() -> None:
    values = np.full(100, 50.0)
    values[40] = 900.0
    assert rolling_median(values)[40] == 50.0
    values[40:56] = 900.0  # 16 of the 31 frames around 48 are high: the median follows them
    assert rolling_median(values)[48] == 900.0
    assert rolling_median(values)[10] == 50.0


def test_line_runs_break_at_a_segment_change_and_a_long_gap() -> None:
    t = np.array([0.0, 0.1, 0.2, 0.3, 5.0, 5.1, 5.2, 9.0])
    seg = np.array([0, 0, 0, 1, 1, 1, 1, 1])
    runs = line_runs(t, seg, gap_s=2.0)
    assert [(r.start, r.stop) for r in runs] == [(0, 3), (3, 4), (4, 7), (7, 8)]
    assert line_runs(np.array([]), np.array([])) == []


def test_median_by_run_never_reaches_across_a_run_boundary() -> None:
    values = np.array([10.0] * 3 + [500.0] * 10)  # a short run, then a long one
    runs = [slice(0, 3), slice(3, 13)]
    assert median_by_run(values, runs, window=9).tolist() == [10.0] * 3 + [500.0] * 10
    assert rolling_median(values, window=9)[2] == 500.0  # one window over both would blend them
    assert np.isnan(median_by_run(np.array([1.0, 2.0]), [slice(0, 1)])[1])  # in no run: no value


def test_row_arrays_leave_keyframes_out_of_the_brightening() -> None:
    rows = _rows()
    rows[25]["brightening"] = 60.0  # a keyframe row that carries a value anyway
    arr = row_arrays(rows)
    assert arr.t.size == len(rows) and arr.dark_px[1] == 110.0
    assert np.isnan(arr.brightening[0]) and np.isnan(arr.brightening[25])  # keyframes
    assert arr.brightening[1] == 4.0 and arr.brightening[2] == 5.0
    assert arr.brightening[rows.index(next(r for r in rows if r["t_s"] == EVENT_T))] == EVENT_PEAK


def test_unit_label_never_claims_celsius_for_counts() -> None:
    assert unit_label("celsius") == "°C"
    assert unit_label("counts") == "counts"


def test_panel_boxes_are_four_stacked_inside_the_margins() -> None:
    boxes = panel_boxes()
    assert len(boxes) == 4
    assert boxes[0][0] == 60 and boxes[-1][1] == PLOT_H - 100  # roi_plot_png's top and bottom
    assert all(b[1] - b[0] > 100 for b in boxes)
    assert all(boxes[i][1] < boxes[i + 1][0] for i in range(3))


# -- the picture --------------------------------------------------------------------------------


def test_plot_png_decodes_with_events(tmp_path: Path) -> None:
    reader = _thermal_run(tmp_path)
    png = visible_sample_plot_png(reader, _rows(), _summary())
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG"
    assert img.size == Image.open(io.BytesIO(roi_plot_png(reader, [SAMPLE]))).size
    assert img.size == (PLOT_W, PLOT_H)
    a = _image(png)
    x = _x_of(EVENT_T)
    for panel, (top, bottom) in enumerate(panel_boxes()):  # every panel has the line
        on_line = _count(a, EVENT_RGB, (top, bottom), (x - 2, x + 3))
        assert on_line > 0.8 * (bottom - top), panel
        beside = _count(a, EVENT_RGB, (top, bottom), (x - 62, x - 40))
        assert beside == 0, panel  # the line only stands where the event is
    key = (panel_boxes()[3][0] - 44, panel_boxes()[3][0] - 20)  # the chip in the bottom legend
    assert _count(a, EVENT_RGB, key, (MARGIN_L, PLOT_W)) > 200


def test_plot_png_labels_each_event_with_its_peak_value(tmp_path: Path) -> None:
    reader = _thermal_run(tmp_path)
    with_event = _image(visible_sample_plot_png(reader, _rows(), _summary()))
    x = _x_of(EVENT_T)
    for panel, (top, _) in enumerate(panel_boxes()):  # text right of the line, top of panel
        label = _count(with_event, EVENT_RGB, (top, top + 40), (x + 5, x + 90))
        assert label > 20, panel


def test_event_label_near_the_right_edge_goes_left_of_its_line(tmp_path: Path) -> None:
    reader = _thermal_run(tmp_path)
    summary = _summary()
    summary["events"][0]["t_peak_s"] = 7.8
    a = _image(visible_sample_plot_png(reader, _rows(), summary))
    x, (top, _) = _x_of(7.8), panel_boxes()[0]
    assert _count(a, EVENT_RGB, (top, top + 40), (x - 90, x - 5)) > 20
    assert _count(a, EVENT_RGB, (top, top + 40), (x + 5, x + 40)) == 0


def test_a_gap_in_the_video_is_a_break_and_a_short_run_has_its_own_median(
    tmp_path: Path,
) -> None:
    """Two segments: 0.3-2.0 s with 100-160 dark pixels, then 3 frames at 6.0 s with 1000."""
    rows = [r for r in _rows() if r["t_s"] <= 2.0]
    for i in range(3):
        rows.append({**rows[1], "t_s": 6.0 + 0.1 * i, "segment": 1, "sample_dark_px": 1000})
    a = _image(visible_sample_plot_png(_thermal_run(tmp_path), rows, _summary()))
    gap = (_x_of(2.5), _x_of(5.5))
    for panel, rgb in ((2, DARK_RGB), (3, BRIGHT_RGB)):
        top, bottom = panel_boxes()[panel]
        assert _count(a, rgb, (top, bottom), (_x_of(0.3), _x_of(2.0))) > 20, panel
        assert _count(a, rgb, (top, bottom), gap) == 0, panel
    top, _ = panel_boxes()[2]  # the 31-frame median of the short run is its own 1000, near the top
    assert _count(a, DARK_RGB, (top, top + 20), (_x_of(6.0) - 3, _x_of(6.2) + 3)) > 20


def test_plot_png_without_rf_or_events(tmp_path: Path) -> None:
    reader = _thermal_run(tmp_path, control=False)
    assert not [e for e in reader.events if e.get("type") == "control"]
    png = visible_sample_plot_png(reader, _rows(), _summary(events=False))
    assert Image.open(io.BytesIO(png)).size == (PLOT_W, PLOT_H)
    a = _image(png)
    assert _count(a, EVENT_RGB, (0, PLOT_H), (0, PLOT_W)) == 0  # no event line, label or key
    assert _panel_count(a, RF_RGB, 0) == 0  # an empty RF panel, not a flat line at zero
    assert _panel_count(a, MAX_RGB, 1) > 100  # the other three panels are drawn
    assert _panel_count(a, DARK_RGB, 2) > 100
    assert _panel_count(a, BRIGHT_RGB, 3) > 100


def test_plot_png_draws_each_series_in_its_own_panel(tmp_path: Path) -> None:
    a = _image(visible_sample_plot_png(_thermal_run(tmp_path), _rows(), _summary()))
    drawn = {0: {RF_RGB}, 1: {MAX_RGB, MEAN_RGB}, 2: {DARK_RGB}, 3: {BRIGHT_RGB}}
    for panel, own in drawn.items():
        for rgb in (RF_RGB, MAX_RGB, MEAN_RGB, DARK_RGB, BRIGHT_RGB):
            n = _panel_count(a, rgb, panel)
            assert n > 100 if rgb in own else n == 0, (panel, rgb, n)


@pytest.mark.parametrize(("high_c", "drawn"), [(30.0, True), (250.0, False), (None, False)])
def test_case_ceiling_is_drawn_only_when_the_max_reaches_it(
    tmp_path: Path, high_c: float | None, drawn: bool
) -> None:
    """The sample max rises from 27 to about 35 C over the run."""
    reader = _thermal_run(tmp_path, high_c=high_c)
    a = _image(visible_sample_plot_png(reader, _rows(), _summary()))
    count = _panel_count(a, CEILING_RGB, 1)
    assert (count > 50) is drawn, count


def test_no_ceiling_for_counts_which_are_not_celsius(tmp_path: Path) -> None:
    """Raw counts (about 29,800) are far above a limit of 30, but a limit in C does not apply."""
    reader = _thermal_run(tmp_path, high_c=30.0, ir_format="Radiometric")
    a = _image(visible_sample_plot_png(reader, _rows(), _summary()))
    assert _panel_count(a, CEILING_RGB, 1) == 0
    assert _panel_count(a, MAX_RGB, 1) > 100


def test_plot_png_fails_loudly_when_the_sample_roi_is_not_in_the_run(tmp_path: Path) -> None:
    summary = {**_summary(), "sample_roi": {"id": 999, "name": "gone"}}
    with pytest.raises(ValueError, match="999"):
        visible_sample_plot_png(_thermal_run(tmp_path), _rows(), summary)


# -- the runner writes it ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def real() -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((FIXTURES / "visible_sample_20261020_144402.json").read_text())
    return doc


@pytest.fixture(scope="module")
def short_clip(tmp_path_factory: pytest.TempPathFactory, real: dict[str, Any]) -> Path:
    """synthetic, 1.5 s: plumbing for the runner, not detection truth."""
    return synthetic_clip(tmp_path_factory.mktemp("short") / "s.mp4", real, 1.5, 0.5)


@pytest.fixture
def fixed_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """The two-level synthetic scene defeats Otsu; these tests are not about the threshold."""
    monkeypatch.setattr(vsr, "otsu_threshold", lambda values: 128)


def _plot_path(d: Path) -> Path:
    return d / "exports" / "visible_sample_plot.png"


@needs_ffmpeg
@pytest.mark.parametrize("closeup", [True, False])
def test_runner_writes_the_plot_on_ok(
    tmp_path: Path, real: dict[str, Any], short_clip: Path, fixed_threshold: None, closeup: bool
) -> None:
    d = experiment(tmp_path, real, [short_clip])
    out = run_analysis(d, closeup=closeup)
    assert out["status"] == "ok" and out["plot_error"] is None, out
    img = Image.open(_plot_path(d))
    assert img.format == "PNG" and img.size == (PLOT_W, PLOT_H)
    assert out["files"][-2:] == ["visible_sample_plot.png", "visible_sample.json"]
    assert exported(d) == sorted(out["files"])  # no .part left, nothing unlisted
    assert json.loads((d / "exports" / "visible_sample.json").read_text()) == out


@needs_ffmpeg
def test_runner_removes_the_plot_when_a_later_run_is_skipped(
    tmp_path: Path, real: dict[str, Any], short_clip: Path, fixed_threshold: None
) -> None:
    d = experiment(tmp_path, real, [short_clip])
    assert run_analysis(d)["status"] == "ok" and _plot_path(d).is_file()
    out = run_analysis(d, ffmpeg="/nonexistent")
    assert out["status"] == "skipped" and out["reason"] == "ffmpeg not found"
    assert not _plot_path(d).exists()
    assert exported(d) == ["visible_sample.json"]


@needs_ffmpeg
def test_runner_keeps_the_analysis_when_only_the_plot_fails(
    tmp_path: Path,
    real: dict[str, Any],
    short_clip: Path,
    fixed_threshold: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The plot is derived from the CSV and the summary: losing it must not lose them, but the
    summary must say it is missing, and an older plot must not stand in for it."""
    d = experiment(tmp_path, real, [short_clip])
    assert run_analysis(d)["status"] == "ok" and _plot_path(d).is_file()

    def fails(*args: Any, **kw: Any) -> bytes:
        raise RuntimeError("no font")

    monkeypatch.setattr(vsr, "visible_sample_plot_png", fails)
    out = run_analysis(d)
    assert out["status"] == "ok" and out["reason"] is None
    assert out["plot_error"] == "RuntimeError: no font"
    assert "visible_sample_plot.png" not in out["files"]
    assert not _plot_path(d).exists()  # the plot of the first run is gone, not left to mislead
    assert exported(d) == sorted(out["files"])
    assert (d / "exports" / "visible_sample.csv").is_file() and out["coverage"]["frames_analysed"]
    assert json.loads((d / "exports" / "visible_sample.json").read_text()) == out
