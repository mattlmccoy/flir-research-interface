"""Derived thermal preview video (exports/thermal_preview.mp4): colourised, for viewing only."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from flir_research_interface.analysis.thermal_video import (
    encode_command,
    render_thermal_video,
    thermal_frame_rgb,
)
from flir_research_interface.camera.base import Frame
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.recording.recorder import Recorder
from flir_research_interface.visible.recorder import FFMPEG_CANDIDATES
from flir_research_interface.visible.rtsp import find_ffprobe

W, H = 64, 48


def _make_experiment(root: Path, n: int = 12) -> Path:
    rec = Recorder(None, experiments_root=root, chunk_frames=4, min_free_gb=0.0)
    d = rec.start(
        name="vid", metadata={}, camera_info={"ir_format": "TemperatureLinear10mK", "model": "Sim"}
    )
    for i in range(n):
        counts = np.full((H, W), 29815, dtype=np.uint16)
        counts[10:30, 20:44] = 29815 + 500 * (i + 1)  # 5 °C hotter per frame
        rec.submit(
            Frame(
                frame_id=i,
                device_timestamp_ns=i * 33_333_333,
                host_timestamp_ns=i,
                pixel_format="Mono16",
                ir_format="TemperatureLinear10mK",
                counts=counts,
                incomplete=False,
            )
        )
    rec.stop()
    return d


def test_thermal_frame_rgb_paints_hot_bright_with_a_colourbar_and_label() -> None:
    celsius = np.full((H, W), 25.0, dtype=np.float32)
    celsius[10:30, 20:44] = 80.0
    rgb = thermal_frame_rgb(celsius, vmin=20.0, vmax=90.0, t_s=1.5, bar_px=16)
    assert rgb.dtype == np.uint8 and rgb.shape == (H, W + 16, 3)
    hot, cold = rgb[20, 30].astype(int), rgb[40, 5].astype(int)
    assert hot.sum() > cold.sum() + 200  # iron palette: hot is bright, cold is dark
    bar = rgb[:, W:, :]
    assert bar[2, 8].astype(int).sum() > bar[H - 3, 8].astype(int).sum()  # top = vmax = bright


def test_encode_command_is_h264_yuv420p_rawvideo_pipe(tmp_path: Path) -> None:
    cmd = encode_command("/opt/ffmpeg", W + 16, H, fps=30.0, out=tmp_path / "x.mp4")
    joined = " ".join(cmd)
    assert "-f rawvideo" in joined and "-pix_fmt rgb24" in joined and f"-s {W + 16}x{H}" in joined
    assert "-c:v libx264" in joined and "-pix_fmt yuv420p" in joined and "+faststart" in joined
    assert cmd[cmd.index("-r") + 1] == "30" and cmd[-1] == str(tmp_path / "x.mp4")


@pytest.mark.skipif(find_ffprobe(FFMPEG_CANDIDATES) is None, reason="ffmpeg not installed")
def test_render_thermal_video_writes_a_playable_mp4_next_to_the_store(tmp_path: Path) -> None:
    d = _make_experiment(tmp_path)
    r = ExperimentReader(d)
    info = render_thermal_video(r)
    out = Path(info["path"])
    assert out == d / "exports" / "thermal_preview.mp4" and out.stat().st_size > 500
    assert info["frames"] == 12 and info["units"] == "celsius"
    assert info["vmin"] == pytest.approx(25.0, abs=0.05)
    assert (
        25.0 < info["vmax"] <= 85.05
    )  # robust (percentile) scale: a lone hot block does not dominate
    ffprobe = find_ffprobe()
    assert ffprobe
    import subprocess

    meta = json.loads(
        subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-count_frames",
                "-show_entries",
                "stream=codec_name,width,height,nb_read_frames",
                "-of",
                "json",
                str(out),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )["streams"][0]
    assert meta["codec_name"] == "h264" and int(meta["nb_read_frames"]) == 12
    assert meta["width"] % 2 == 0 and meta["height"] % 2 == 0  # yuv420p needs even dimensions


def test_label_font_has_the_degree_and_dash_glyphs() -> None:
    from PIL import ImageFont

    from flir_research_interface.analysis.thermal_video import label_font

    f = label_font()
    assert isinstance(f, ImageFont.FreeTypeFont)  # the bitmap default lacks ° (draws a box)
    assert f.getlength("15.0 to 25.3 °C") > f.getlength("15.0")
