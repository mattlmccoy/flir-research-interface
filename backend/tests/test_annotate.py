"""Publication-grade derived images per run: native-resolution frames (upscaled 2x) with and
without ROI annotations, a colour bar and a caption; the same overlay drawn into the video."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from flir_research_interface.analysis.annotate import (
    annotated_frame,
    draw_rois,
    write_annotated_frames,
)
from flir_research_interface.playback.reader import ExperimentReader
from tests.test_run_summary import _exp


def test_draw_rois_outlines_in_the_roi_colour_with_label(tmp_path: Path) -> None:
    img = Image.new("RGB", (64, 48), (0, 0, 0))
    rois = [
        {
            "id": 2,
            "kind": "rect",
            "x0": 4,
            "y0": 4,
            "x1": 20,
            "y1": 16,
            "name": "sample",
            "color": "#ff8ad8",
        }
    ]
    draw_rois(img, rois, scale=1, values={2: "31.2 °C"})
    a = np.asarray(img)
    assert tuple(a[4, 10]) == (0xFF, 0x8A, 0xD8), "top edge drawn in the ROI colour"
    assert a[6:14, 6:18, :].sum() > 0, "label text drawn (inside the box, which is otherwise black)"


def test_annotated_frame_is_2x_native_with_bar_and_caption_and_rois(tmp_path: Path) -> None:
    r = _exp(tmp_path)  # 16x16 frames, 2 ROIs stored in metadata
    clean = annotated_frame(r, index=5, scale=2, with_rois=False)
    ann = annotated_frame(r, index=5, scale=2, with_rois=True)
    assert clean.width >= 32 + 40 and clean.height >= 32 + 20  # 2x image + colour bar + caption
    assert ann.size == clean.size
    assert np.asarray(ann).astype(int).sum() != np.asarray(clean).astype(int).sum(), (
        "ROIs change pixels"
    )


def test_write_annotated_frames_creates_peak_frame_files(tmp_path: Path) -> None:
    r = _exp(tmp_path)
    out = write_annotated_frames(r)
    assert (
        Path(out["peak_rois"]).name == "peak_frame_rois.png"
        and Path(out["peak_clean"]).name == "peak_frame.png"
    )
    assert out["peak_index"] == r.n_frames - 1  # the ramp peaks on the last frame
    im = Image.open(out["peak_rois"])
    assert im.width >= 32 and im.format == "PNG"
    r2 = ExperimentReader(r.path)
    assert r2.n_frames == r.n_frames  # store untouched
