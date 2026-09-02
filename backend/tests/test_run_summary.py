"""Per-run README.txt (plain-prose metadata) and roi_plot.png (ROI traces + marks)."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image

from flir_research_interface.analysis.run_summary import (
    readme_text,
    roi_plot_png,
    write_run_summary,
)
from flir_research_interface.camera.base import Frame
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.recording.recorder import Recorder

ROIS = [
    {"id": 1, "kind": "spot", "x": 5, "y": 5, "name": "centre"},
    {"id": 2, "kind": "rect", "x0": 0, "y0": 0, "x1": 8, "y1": 8, "color": "#ff8ad8"},
]


def _exp(root: Path, n: int = 10, rois: list | None = ROIS) -> ExperimentReader:
    rec = Recorder(None, experiments_root=root, chunk_frames=4, min_free_gb=0.0)
    d = rec.start(
        name="sum",
        metadata={"operator": "mm", "material": "PA12", "rf_frequency_mhz": 13.56},
        camera_info={
            "model": "FLIR A70",
            "serial": "123",
            "ir_format": "TemperatureLinear10mK",
            "lens": "FOL08",
            "frame_rate_hz": 30.0,
            "active_case": {"index": 1, "low_c": -20.0, "high_c": 250.0},
            "object_parameters": {
                "ObjectEmissivity": 0.949999988079071,
                "ReflectedTemperature": 293.15,
                "ObjectDistance": 0.4445,
            },
        },
        extra={"rois": rois} if rois else None,
    )
    for i in range(n):
        rec.submit(
            Frame(
                frame_id=i,
                device_timestamp_ns=i * 33_333_333,
                host_timestamp_ns=i,
                pixel_format="Mono16",
                ir_format="TemperatureLinear10mK",
                counts=np.full((16, 16), 29815 + 100 * i, dtype=np.uint16),
                incomplete=False,
            )
        )
        if i == 4:
            rec.note_event("annotation", {"name": "RF ON", "note": "go"})
        if i == 6:  # a fake NUC-length freeze so the plot marks it
            frozen = {"first_frame_id": 6, "last_frame_id": 8, "repeats": 12}
            rec.note_event("frozen_frames", frozen)
    rec.stop()
    return ExperimentReader(d)


def test_readme_is_plain_prose_with_the_facts_a_reader_needs(tmp_path: Path) -> None:
    txt = readme_text(_exp(tmp_path))
    for needle in (
        "sum",
        "FLIR A70",
        "10 frames",
        "TemperatureLinear10mK",
        "0.01",
        "273.15",
        "PA12",
        "13.56",
        "emissivity",
        "0.95",
        "centre",
        "RF ON",
        "thermal.zarr",
        "roi_series.csv",
        "thermal_preview.mp4",
    ):
        assert needle in txt, needle
    assert "{" not in txt  # prose, not a JSON dump


def test_roi_plot_is_a_png_with_one_trace_per_roi_and_the_marks(tmp_path: Path) -> None:
    r = _exp(tmp_path)
    from flir_research_interface.analysis.run_summary import plot_marks

    assert [m[1] for m in plot_marks(r)] == ["RF ON", "NUC (12 fr)"]
    png = roi_plot_png(r, r.metadata["rois"])
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG" and img.width >= 800 and img.height >= 300
    a = np.asarray(img.convert("RGB")).astype(int)
    pink = (
        (abs(a[..., 0] - 0xFF) < 40) & (abs(a[..., 1] - 0x8A) < 40) & (abs(a[..., 2] - 0xD8) < 40)
    ).sum()
    assert pink > 50  # rect ROI drawn in its own colour


def test_write_run_summary_puts_both_files_in_exports_and_skips_plot_without_rois(
    tmp_path: Path,
) -> None:
    r = _exp(tmp_path)
    out = write_run_summary(r)
    assert (r.path / "README.txt").is_file() and (r.path / "exports" / "roi_plot.png").is_file()
    assert out == {
        "readme": str(r.path / "README.txt"),
        "roi_plot": str(r.path / "exports" / "roi_plot.png"),
    }
    r2 = _exp(tmp_path / "b", rois=None)
    assert write_run_summary(r2) == {"readme": str(r2.path / "README.txt"), "roi_plot": None}
