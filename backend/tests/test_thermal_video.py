"""Derived thermal preview video (exports/thermal_preview.mp4): colorised, for viewing only."""

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


def test_thermal_frame_rgb_paints_hot_bright_with_a_colorbar_and_label() -> None:
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


@pytest.mark.skipif(find_ffprobe(FFMPEG_CANDIDATES) is None, reason="ffmpeg not installed")
def test_render_reports_monotonic_progress_up_to_the_frame_count(tmp_path: Path) -> None:
    """The slow ROI-video render must report progress so the UI can show a determinate bar."""
    d = _make_experiment(tmp_path, n=12)
    reader = ExperimentReader(d)
    seen: list[tuple[int, int]] = []
    render_thermal_video(reader, on_progress=lambda done, total: seen.append((done, total)))
    assert seen, "on_progress was never called"
    assert all(total == 12 for _, total in seen), "total is the frame count"
    assert seen == sorted(seen), "progress is monotonic"
    assert seen[-1][0] == 12, "progress reaches every frame"


def test_run_range_reports_progress_over_all_frames(tmp_path: Path) -> None:
    """run_range scans every frame; it must report monotonic done→total for a progress bar."""
    from flir_research_interface.analysis.thermal_video import run_range

    d = _make_experiment(tmp_path, n=70)  # > BLOCK (64) so several blocks report progress
    reader = ExperimentReader(d)
    seen: list[tuple[int, int]] = []
    run_range(reader, robust=True, on_progress=lambda done, total: seen.append((done, total)))
    assert len(seen) >= 2, "multi-block scan reports progress more than once"
    assert all(total == reader.n_frames for _, total in seen), "total is the frame count"
    assert seen == sorted(seen), "progress is monotonic"
    assert seen[-1] == (reader.n_frames, reader.n_frames), "progress reaches the last frame"


def test_save_and_load_range_roundtrip_and_staleness(tmp_path: Path) -> None:
    """save_range writes range.json; load_range returns it only when n_frames still matches."""
    from flir_research_interface.analysis.thermal_video import (
        load_range,
        run_range,
        save_range,
    )

    d = _make_experiment(tmp_path, n=20)
    reader = ExperimentReader(d)
    assert load_range(reader) is None, "no cache file yet → None"

    lo, hi, units = run_range(reader, robust=True)
    save_range(reader, lo, hi, units)
    got = load_range(reader)
    assert got is not None
    assert got["vmin"] == lo and got["vmax"] == hi and got["units"] == units
    assert got["n_frames"] == reader.n_frames

    # Simulate the run growing (more frames appended): the cached range is stale, so it's ignored.
    stale = json.loads((d / "exports" / "range.json").read_text())
    stale["n_frames"] = reader.n_frames + 5
    (d / "exports" / "range.json").write_text(json.dumps(stale))
    assert load_range(reader) is None, "n_frames mismatch → stale → None"


def test_encode_temp_lives_outside_the_experiment_dir() -> None:
    """Partial encodes must NOT be written inside exports/ (which may be a Dropbox-synced folder):
    Dropbox racing the .part file mid-encode caused ffmpeg 'unable to re-open output' failures and
    orphaned .part.mp4 files. The temp must live in the system temp dir instead."""
    import tempfile as _t

    from flir_research_interface.analysis.thermal_video import _encode_tmp

    p = _encode_tmp(".mp4")
    try:
        assert p.suffix == ".mp4"
        assert str(p).startswith(str(_t.gettempdir())), f"{p} is not under the system temp dir"
    finally:
        p.unlink(missing_ok=True)
