"""Display paths read the camera's visible video as full range (Y 0-255).

The A70 stream is full-range luma but untagged, so players and ffmpeg treat it as TV range and clip
everything >= 235 to white. ``full_range_copy`` makes a lossless copy tagged full range; the MJPEG
preview and the overlay frame extraction declare the input full range. The clips here are
synthetic (ffmpeg lavfi test patterns): they check tagging and plumbing, not the camera's output.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from flir_research_interface.analysis import visible_overlay
from flir_research_interface.api.app import create_app
from flir_research_interface.camera.base import Frame
from flir_research_interface.recording.recorder import Recorder
from flir_research_interface.visible import full_range
from flir_research_interface.visible.full_range import full_range_copy
from flir_research_interface.visible.preview import mjpeg_command
from flir_research_interface.visible.recorder import FFMPEG_CANDIDATES
from flir_research_interface.visible.rtsp import find_ffprobe

FFMPEG = find_ffprobe(FFMPEG_CANDIDATES)
FFPROBE = find_ffprobe()
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None or FFPROBE is None, reason="ffmpeg not installed")


def _synthetic_clip(path: Path) -> None:
    """A 1 s, 10 fps H.264 clip with no colour-range tag (synthetic test pattern)."""
    assert FFMPEG is not None
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "testsrc=size=128x96:rate=10:duration=1", "-pix_fmt", "yuv420p",
         "-c:v", "libx264", "-g", "5", str(path)],
        check=True,
    )  # fmt: skip


def _probe(path: Path, show: str, section: str) -> list[dict[str, Any]]:
    assert FFPROBE is not None
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0", "-of", "json",
         "-show_entries", f"{section}={show}", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    rows: list[dict[str, Any]] = json.loads(out)[f"{section}s"]
    return rows


def _run_dir(root: Path) -> Path:
    """A finalized one-frame recording (so the API can open it) with no visible video yet."""
    rec = Recorder(None, experiments_root=root, chunk_frames=4)
    d = rec.start(name="vis", metadata={}, camera_info={"ir_format": "TemperatureLinear10mK"})
    rec.submit(
        Frame(
            frame_id=1, device_timestamp_ns=1, host_timestamp_ns=1, pixel_format="Mono16",
            ir_format="TemperatureLinear10mK", counts=np.zeros((4, 4), dtype=np.uint16),
            incomplete=False,
        )
    )
    rec.stop()
    return d


@needs_ffmpeg
def test_full_range_copy_tags_pc_and_keeps_packets(tmp_path: Path) -> None:
    run = _run_dir(tmp_path)
    _synthetic_clip(run / "visible.mp4")
    assert _probe(run / "visible.mp4", "color_range", "stream")[0].get("color_range") in (
        None, "unknown", "tv",
    )

    out = full_range_copy(run, "visible.mp4", FFMPEG)

    assert out == run / "exports" / "visible_full_range.mp4" and out.is_file()
    assert _probe(out, "color_range", "stream")[0]["color_range"] == "pc"
    src = _probe(run / "visible.mp4", "size,pts_time", "packet")
    dst = _probe(out, "size,pts_time", "packet")
    assert len(src) == len(dst) == 10
    assert [p["size"] for p in dst] == [p["size"] for p in src]  # lossless: same packets
    assert [p["pts_time"] for p in dst] == [p["pts_time"] for p in src]  # and same timing
    assert not list((run / "exports").glob("*.part*"))


@needs_ffmpeg
def test_full_range_copy_names_segments(tmp_path: Path) -> None:
    run = _run_dir(tmp_path)
    _synthetic_clip(run / "visible_001.mp4")
    out = full_range_copy(run, "visible_001.mp4", FFMPEG)
    assert out == run / "exports" / "visible_001_full_range.mp4" and out.is_file()


@needs_ffmpeg
def test_full_range_copy_reused_and_rebuilt_when_source_newer(tmp_path: Path) -> None:
    run = _run_dir(tmp_path)
    src = run / "visible.mp4"
    _synthetic_clip(src)
    out = full_range_copy(run, "visible.mp4", FFMPEG)
    assert out is not None
    os.utime(out, (out.stat().st_atime, src.stat().st_mtime + 100))  # copy newer than source
    stamp = out.stat().st_mtime_ns

    again = full_range_copy(run, "visible.mp4", "/nonexistent")  # a rebuild would need ffmpeg
    assert again == out and out.stat().st_mtime_ns == stamp  # reused, not rebuilt

    os.utime(src, (src.stat().st_atime, out.stat().st_mtime + 100))  # source now newer
    rebuilt = full_range_copy(run, "visible.mp4", FFMPEG)
    assert rebuilt == out and out.stat().st_mtime_ns != stamp
    assert _probe(out, "color_range", "stream")[0]["color_range"] == "pc"


def test_full_range_copy_is_none_without_ffmpeg(tmp_path: Path) -> None:
    run = _run_dir(tmp_path)
    (run / "visible.mp4").write_bytes(b"not a video")
    assert full_range_copy(run, "visible.mp4", "/nonexistent") is None
    assert full_range_copy(run, "visible.mp4", None) is None or FFMPEG is not None


@needs_ffmpeg
def test_full_range_copy_is_none_and_leaves_nothing_when_the_build_fails(tmp_path: Path) -> None:
    run = _run_dir(tmp_path)
    (run / "visible.mp4").write_bytes(b"not a video")  # ffmpeg cannot remux this
    assert full_range_copy(run, "visible.mp4", FFMPEG) is None
    assert list((run / "exports").glob("*")) == []  # no half-written copy left behind


def _app(root: Path) -> TestClient:
    return TestClient(create_app(default_backend="simulated", experiments_root=root))


@needs_ffmpeg
def test_visible_route_serves_full_range_copy(tmp_path: Path) -> None:
    run = _run_dir(tmp_path)
    _synthetic_clip(run / "visible.mp4")
    with _app(tmp_path) as c:
        info = c.get(f"/api/experiments/{run.name}").json()
        r = c.get(f"/api/experiments/{run.name}/visible.mp4")
        seg = c.get(f"/api/experiments/{run.name}/visible/0")
        part = c.get(f"/api/experiments/{run.name}/visible.mp4", headers={"Range": "bytes=0-99"})
    assert r.status_code == 200 and r.headers["x-visible-range"] == "full"
    assert seg.status_code == 200 and seg.headers["x-visible-range"] == "full"
    assert info["visible_range"] == "full"
    assert r.content == (run / "exports" / "visible_full_range.mp4").read_bytes()
    assert part.status_code == 206 and len(part.content) == 100  # seeking still works


@pytest.mark.parametrize("ffmpeg", [None, "/nonexistent"])
def test_visible_route_falls_back_to_raw_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ffmpeg: str | None
) -> None:
    monkeypatch.setattr(full_range, "resolve_ffmpeg", lambda: ffmpeg)
    run = _run_dir(tmp_path)
    (run / "visible.mp4").write_bytes(bytes(range(256)) * 4)
    with _app(tmp_path) as c:
        r = c.get(f"/api/experiments/{run.name}/visible.mp4")
        seg = c.get(f"/api/experiments/{run.name}/visible/0")
        info = c.get(f"/api/experiments/{run.name}").json()
    assert r.status_code == 200 and r.content == bytes(range(256)) * 4
    assert r.headers["x-visible-range"] == "raw-untagged"
    assert seg.headers["x-visible-range"] == "raw-untagged"
    if ffmpeg is None:  # a missing binary is known up front; a broken path only on first use
        assert info["visible_range"] == "raw-untagged"  # matches what the route serves
    assert not (run / "exports" / "visible_full_range.mp4").exists()


def test_visible_range_is_null_without_a_visible_video(tmp_path: Path) -> None:
    run = _run_dir(tmp_path)
    with _app(tmp_path) as c:
        assert c.get(f"/api/experiments/{run.name}").json()["visible_range"] is None


def test_visible_route_serves_raw_when_the_build_fails(tmp_path: Path) -> None:
    run = _run_dir(tmp_path)
    (run / "visible.mp4").write_bytes(b"not a video")  # ffmpeg (if any) cannot remux this
    with _app(tmp_path) as c:
        r = c.get(f"/api/experiments/{run.name}/visible.mp4")
    assert r.status_code == 200 and r.content == b"not a video"
    assert r.headers["x-visible-range"] == "raw-untagged"


def test_mjpeg_command_reads_full_range() -> None:
    cmd = mjpeg_command("/opt/ffmpeg", "rtsp://u:p@h/avc/ch1", fps=8, width=640)
    assert cmd[cmd.index("-vf") + 1] == "scale=640:-2:in_range=full:out_range=full"


def test_overlay_extraction_reads_full_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "visible.mp4").write_bytes(b"x")
    reader = SimpleNamespace(
        path=tmp_path,
        host_t0_ns=None,
        visible={"file": "visible.mp4", "duration_s": 10.0, "measured_fps": 6.0,
                 "width": 128, "height": 96},
        metadata={"visible_alignment": {"H": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}},
    )
    argvs: list[list[str]] = []

    def fake_run(cmd: list[str], **_: Any) -> None:
        argvs.append(cmd)

    monkeypatch.setattr(visible_overlay.subprocess, "run", fake_run)
    with visible_overlay.VisibleSource(reader, "ffmpeg", 1.0, 2.0, 64, 48):
        pass
    assert len(argvs) == 1
    vf = argvs[0][argvs[0].index("-vf") + 1]
    assert vf.startswith("scale=in_range=full:out_range=full,fps=")
    assert argvs[0][argvs[0].index("-i") + 1] == str(tmp_path / "visible.mp4")  # raw file read
