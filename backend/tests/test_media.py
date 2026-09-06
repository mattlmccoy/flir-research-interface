"""Media export: windowed clip (mp4/gif) with overlays, and the ROI-stats companion."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from flir_research_interface.camera.base import Frame
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.recording.recorder import Recorder
from flir_research_interface.visible.recorder import FFMPEG_CANDIDATES
from flir_research_interface.visible.rtsp import find_ffprobe

_HAVE_FFMPEG = find_ffprobe(FFMPEG_CANDIDATES) is not None
W, H = 64, 48


def _make(root: Path, n: int = 20) -> ExperimentReader:
    rec = Recorder(None, experiments_root=root, chunk_frames=4, min_free_gb=0.0)
    d = rec.start(name="clip", metadata={},
                  camera_info={"ir_format": "TemperatureLinear10mK", "model": "Sim"})
    for i in range(n):
        counts = np.full((H, W), 29815, dtype=np.uint16)
        counts[10:30, 20:44] = 29815 + 400 * (i + 1)
        rec.submit(Frame(frame_id=i, device_timestamp_ns=i * 33_333_333, host_timestamp_ns=i,
                         pixel_format="Mono16", ir_format="TemperatureLinear10mK",
                         counts=counts, incomplete=False))
    rec.stop()
    return ExperimentReader(d)


def test_clip_window_validation(tmp_path: Path) -> None:
    from flir_research_interface.analysis.media import MediaOptions, render_clip
    r = _make(tmp_path)
    with pytest.raises(ValueError):
        render_clip(r, MediaOptions(start=10, stop=5))  # stop <= start
    with pytest.raises(ValueError):
        render_clip(r, MediaOptions(start=0, stop=999))  # beyond n_frames


@pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg not installed")
def test_clip_renders_mp4_for_the_window(tmp_path: Path) -> None:
    from flir_research_interface.analysis.media import MediaOptions, render_clip
    r = _make(tmp_path)
    seen: list[tuple[int, int]] = []
    info = render_clip(r, MediaOptions(start=4, stop=16, fmt="mp4", title="Test clip"),
                       on_progress=lambda d, t: seen.append((d, t)))
    out = Path(info["path"])
    assert out.is_file() and out.suffix == ".mp4" and out.stat().st_size > 0
    assert info["frames"] == 12
    assert seen and seen[-1][0] == seen[-1][1] == 12


@pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg not installed")
def test_clip_renders_gif_with_size_guard(tmp_path: Path) -> None:
    from flir_research_interface.analysis.media import MediaOptions, render_clip
    r = _make(tmp_path)
    info = render_clip(r, MediaOptions(start=0, stop=20, fmt="gif", scale=2))
    out = Path(info["path"])
    assert out.is_file() and out.suffix == ".gif" and out.stat().st_size > 0


@pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg not installed")
def test_media_export_api_job(tmp_path: Path) -> None:
    import time

    from fastapi.testclient import TestClient

    from flir_research_interface.api.app import create_app

    with TestClient(create_app(default_backend="simulated", sim_fps=60.0,
                               experiments_root=tmp_path, min_free_gb=0.0)) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        rec = c.post("/api/recording/start", json={"name": "clip"}).json()
        name = Path(rec["experiment_dir"]).name
        time.sleep(0.3)
        c.post("/api/recording/stop")
        c.post("/api/camera/disconnect")
        r = c.post(f"/api/experiments/{name}/export/media",
                   json={"start": 0, "stop": 8, "fmt": "gif", "title": "My clip",
                         "frame_stats": True})
        assert r.status_code == 200 and r.json()["state"] == "running"
        t0 = time.monotonic()
        while time.monotonic() - t0 < 30:
            job = c.get(f"/api/experiments/{name}/export/media/status").json()
            if job["state"] in ("done", "error"):
                break
            time.sleep(0.1)
        assert job["state"] == "done", job
        fname = job["file"]["name"]
        assert fname.endswith(".gif")
        assert c.get(f"/api/experiments/{name}/exports/clips/{fname}").status_code == 200


def test_range_compute_job_reports_progress_then_done(tmp_path: Path) -> None:
    """The range-compute endpoint runs the whole-run scan as a job with progress, then reports done;
    a second call is instant (persisted range.json) so the editor's progress bar shows only once."""
    import time

    from fastapi.testclient import TestClient

    from flir_research_interface.api.app import create_app

    with TestClient(create_app(default_backend="simulated", sim_fps=60.0,
                               experiments_root=tmp_path, min_free_gb=0.0)) as c:
        devs = c.get("/api/camera/devices").json()
        c.post("/api/camera/connect", json={"backend": "simulated", "serial": devs[0]["serial"]})
        rec = c.post("/api/recording/start", json={"name": "clip"}).json()
        name = Path(rec["experiment_dir"]).name
        time.sleep(0.3)
        c.post("/api/recording/stop")
        c.post("/api/camera/disconnect")

        started = c.post(f"/api/experiments/{name}/range/compute").json()
        assert started["state"] in ("running", "done")
        total = started["total"]
        assert total > 0
        t0 = time.monotonic()
        while time.monotonic() - t0 < 30:
            job = c.get(f"/api/experiments/{name}/range/status").json()
            if job["state"] in ("done", "error"):
                break
            time.sleep(0.05)
        assert job["state"] == "done", job
        assert job["done"] == job["total"] == total
        # persisted → a fresh status (idempotent) still reports done with the full count
        again = c.post(f"/api/experiments/{name}/range/compute").json()
        assert again == {"state": "done", "done": total, "total": total, "error": None}


@pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg not installed")
def test_media_preview_returns_png(tmp_path: Path) -> None:
    from flir_research_interface.analysis.media import MediaOptions, compose_preview
    r = _make(tmp_path)
    png = compose_preview(r, MediaOptions(scale=1, frame_stats=True, title="Hi"), 5)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg not installed")
def test_live_plot_panel_extends_frame_height(tmp_path: Path) -> None:
    """The live plot is a full-width strip appended below the frame, not an overlay inset."""
    import json
    from io import BytesIO

    from PIL import Image

    from flir_research_interface.analysis.media import MediaOptions, compose_preview
    r = _make(tmp_path)
    meta = json.loads((r.path / "metadata.json").read_text())
    meta["rois"] = [
        {"id": 1, "kind": "rect", "x0": 20, "y0": 10, "x1": 44, "y1": 30, "name": "box"}
    ]
    (r.path / "metadata.json").write_text(json.dumps(meta))
    r2 = ExperimentReader(r.path)
    plain = compose_preview(r2, MediaOptions(start=0, stop=20), 10)
    with_plot = compose_preview(r2, MediaOptions(start=0, stop=20, plot_roi=1), 10)
    assert plain[:8] == b"\x89PNG\r\n\x1a\n" and with_plot[:8] == b"\x89PNG\r\n\x1a\n"
    pw, ph = Image.open(BytesIO(plain)).size
    ww, wh = Image.open(BytesIO(with_plot)).size
    assert ww == pw  # same width
    assert wh > ph  # taller: the plot panel is appended below the image


@pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg not installed")
def test_compose_handles_over_range_frames(tmp_path: Path) -> None:
    """Over-range (saturated) pixels get painted magenta without a read-only-array crash."""
    from flir_research_interface.analysis.media import MediaOptions, compose_preview
    rec = Recorder(None, experiments_root=tmp_path, chunk_frames=4, min_free_gb=0.0)
    d = rec.start(name="hot", metadata={},
                  camera_info={"ir_format": "TemperatureLinear10mK", "model": "Sim"})
    for i in range(8):
        counts = np.full((H, W), 29815, dtype=np.uint16)
        counts[10:30, 20:44] = 65535  # saturated -> over-range mask flags these
        rec.submit(Frame(frame_id=i, device_timestamp_ns=i * 33_333_333, host_timestamp_ns=i,
                         pixel_format="Mono16", ir_format="TemperatureLinear10mK",
                         counts=counts, incomplete=False))
    rec.stop()
    png = compose_preview(ExperimentReader(d), MediaOptions(start=0, stop=8, scale=2), 4)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def _two_rect_reader(tmp_path: Path) -> ExperimentReader:
    import json
    r = _make(tmp_path)
    meta = json.loads((r.path / "metadata.json").read_text())
    meta["rois"] = [
        {"id": 1, "kind": "rect", "x0": 20, "y0": 10, "x1": 44, "y1": 30, "name": "hot"},
        {"id": 2, "kind": "rect", "x0": 0, "y0": 0, "x1": 10, "y1": 10, "name": "cool"},
    ]
    (r.path / "metadata.json").write_text(json.dumps(meta))
    return ExperimentReader(r.path)


def test_plot_traces_multi_roi_distinct_colors_and_labels(tmp_path: Path) -> None:
    """Several selected ROIs each get their own series and a distinct color."""
    from flir_research_interface.analysis.media import MediaOptions, _plot_traces
    r2 = _two_rect_reader(tmp_path)
    traces = _plot_traces(r2, MediaOptions(start=0, stop=20, plot_rois=(1, 2)))
    assert len(traces) == 2
    labels = [t["label"] for t in traces]
    assert any("hot" in x for x in labels) and any("cool" in x for x in labels)
    assert traces[0]["color"] != traces[1]["color"]  # matches the overlay palette by index
    assert len(traces[0]["v"]) == len(traces[0]["t"]) > 0


def test_plot_stats_min_max_mean_each_make_a_line(tmp_path: Path) -> None:
    """Selecting several stats draws one line per (ROI, stat)."""
    from flir_research_interface.analysis.media import MediaOptions, _plot_traces
    r2 = _two_rect_reader(tmp_path)
    traces = _plot_traces(r2, MediaOptions(start=0, stop=20, plot_rois=(1,),
                                           plot_stats=("mean", "min", "max")))
    assert len(traces) == 3
    joined = " ".join(t["label"] for t in traces)
    assert "mean" in joined and "min" in joined and "max" in joined


@pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg not installed")
def test_timestamp_toggle_actually_removes_the_time(tmp_path: Path) -> None:
    """The timestamp checkbox must change the frame (it was baked in unconditionally)."""
    from flir_research_interface.analysis.media import MediaOptions, compose_preview
    r = _make(tmp_path)
    on = compose_preview(r, MediaOptions(start=0, stop=20, timestamp=True, colorbar=False), 5)
    off = compose_preview(r, MediaOptions(start=0, stop=20, timestamp=False, colorbar=False), 5)
    assert on != off  # turning the timestamp off changes the rendered frame


@pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg not installed")
def test_title_does_not_cover_the_timestamp(tmp_path: Path) -> None:
    """A title caption must not paint over the elapsed-time label (they shared the top-left)."""
    from flir_research_interface.analysis.media import MediaOptions, compose_preview
    r = _make(tmp_path)
    with_ts = compose_preview(
        r, MediaOptions(start=0, stop=20, title="Run A", timestamp=True, colorbar=False), 5
    )
    no_ts = compose_preview(
        r, MediaOptions(start=0, stop=20, title="Run A", timestamp=False, colorbar=False), 5
    )
    assert with_ts != no_ts  # the timestamp is still visible when a title is present


def test_plot_series_gives_each_roi_its_own_stats(tmp_path: Path) -> None:
    """plot_series lets each ROI choose its own stats: ROI 1 mean+max, ROI 2 min only."""
    from flir_research_interface.analysis.media import MediaOptions, _plot_traces
    r2 = _two_rect_reader(tmp_path)
    opts = MediaOptions(start=0, stop=20,
                        plot_series=((1, "mean"), (1, "max"), (2, "min")))
    traces = _plot_traces(r2, opts)
    labels = [t["label"] for t in traces]
    assert labels == ["hot · mean", "hot · max", "cool · min"]


def test_overlay_rois_filters_which_boxes_draw(tmp_path: Path) -> None:
    """overlay_rois limits the ROI boxes drawn on the frame; colors stay index-stable."""
    from flir_research_interface.analysis.media import MediaOptions, _overlay_rois
    r2 = _two_rect_reader(tmp_path)
    all_boxes = _overlay_rois(r2, MediaOptions())
    assert {b["id"] for b in all_boxes} == {1, 2}  # default: all
    one = _overlay_rois(r2, MediaOptions(overlay_rois=(2,)))
    assert [b["id"] for b in one] == [2]
    # ROI 2's color is the same whether or not ROI 1 is also drawn (explicit color, not by index)
    assert one[0]["color"] == next(b["color"] for b in all_boxes if b["id"] == 2)


def test_plot_roi_singular_still_supported(tmp_path: Path) -> None:
    """The legacy single ``plot_roi``/``plot_stat`` still yields one trace (backward compatible)."""
    import json

    from flir_research_interface.analysis.media import MediaOptions, _plot_traces
    r = _make(tmp_path)
    meta = json.loads((r.path / "metadata.json").read_text())
    meta["rois"] = [
        {"id": 1, "kind": "rect", "x0": 20, "y0": 10, "x1": 44, "y1": 30, "name": "hot"}
    ]
    (r.path / "metadata.json").write_text(json.dumps(meta))
    r2 = ExperimentReader(r.path)
    traces = _plot_traces(r2, MediaOptions(start=0, stop=20, plot_roi=1))
    assert len(traces) == 1 and "hot" in traces[0]["label"]


def test_plot_traces_prefer_precomputed_csv(tmp_path: Path) -> None:
    """When exports/roi_series.csv exists, the trace is read from it (fast path)."""
    from flir_research_interface.analysis.media import MediaOptions, _plot_traces
    r2 = _two_rect_reader(tmp_path)
    exports = r2.path / "exports"
    exports.mkdir(exist_ok=True)
    # a sentinel CSV: constant mean=111 for R1 so we can tell the CSV was used, not recomputed
    rows = ["# ROI series", "# units: celsius",
            "t_s,frame_id,R1_mean,R1_min,R1_max,R1_std,R1_n"]
    rows += [f"{i * 0.1:.3f},{i},111.0,110.0,112.0,0.5,10" for i in range(20)]
    (exports / "roi_series.csv").write_text("\n".join(rows) + "\n")
    traces = _plot_traces(r2, MediaOptions(start=0, stop=20, plot_rois=(1,)))
    assert len(traces) == 1
    assert all(abs(v - 111.0) < 1e-6 for v in traces[0]["v"])  # came from the CSV


def test_cached_range_persists_and_reloads_without_rescan(tmp_path: Path) -> None:
    """_cached_range computes once (reporting progress), persists range.json, then reloads from disk
    on a cold process (cleared in-memory cache) without scanning frames again."""
    from flir_research_interface.analysis import media
    from flir_research_interface.analysis.thermal_video import load_range

    r = _make(tmp_path, n=20)
    media._RANGE_CACHE.clear()
    scan1: list[int] = []
    v1 = media._cached_range(r, on_progress=lambda d, t: scan1.append(d))
    assert scan1, "first computation scans frames and reports progress"
    assert load_range(r) is not None, "range persisted to exports/range.json"

    # Cold process: clear the in-memory cache; the disk cache must serve it with no rescan.
    media._RANGE_CACHE.clear()
    scan2: list[int] = []
    v2 = media._cached_range(r, on_progress=lambda d, t: scan2.append(d))
    assert v2 == v1
    assert scan2 == [], "second call loads range.json — no frame scan"


def test_target_bitrate_bps_hits_the_size_budget() -> None:
    from flir_research_interface.analysis.media import _target_bitrate_bps

    assert _target_bitrate_bps(0, 10.0) == 0          # no limit → 0 (caller skips capping)
    assert _target_bitrate_bps(10_000_000, 0) == 0    # unknown duration → 0
    # 10 MB over 10 s ≈ 8 Mbps before overhead margin; margin trims it a little, floored at 64 kbps
    bps = _target_bitrate_bps(10_000_000, 10.0)
    assert 6_000_000 <= bps <= 8_000_000
    assert _target_bitrate_bps(1_000, 3600.0) == 64_000  # tiny budget → the 64 kbps floor


def test_scaled_even_clamps_and_never_upscales() -> None:
    from flir_research_interface.analysis.media import _scaled_even

    assert _scaled_even(1000, 800, 0.5) == (500, 400)
    assert _scaled_even(1000, 800, 2.0) == (1000, 800)  # never upscales past full size
    w, h = _scaled_even(1000, 800, 0.001)
    assert w >= 2 and h >= 2 and w % 2 == 0 and h % 2 == 0


def test_best_scale_fills_toward_the_cap() -> None:
    from flir_research_interface.analysis.media import _best_scale

    # bytes ∝ area: full size = 10 MB; the largest scale under a 4 MB cap is √(4/10) ≈ 0.632
    def measure(s: float) -> int:
        return int(10_000_000 * s * s)

    target = 4_000_000
    s = _best_scale(measure, target, seed=1.0)
    assert measure(s) <= target and s >= 0.55  # under the cap AND near the boundary (not tiny)
    s2 = _best_scale(measure, target, seed=0.1)  # a small seed must still climb toward the cap
    assert measure(s2) <= target and s2 >= 0.55
    assert _best_scale(lambda s: int(1000 * s), target=5000, seed=1.0) == 1.0  # full res fits


def test_encode_command_adds_a_bitrate_cap_only_when_requested() -> None:
    from flir_research_interface.analysis.thermal_video import encode_command

    capped = " ".join(str(c) for c in encode_command("/x/ffmpeg", 100, 100, 30,
                                                      Path("/tmp/o.mp4"), maxrate_bps=800_000))
    assert "-maxrate 800000" in capped and "-bufsize 1600000" in capped
    uncapped = " ".join(str(c) for c in encode_command("/x/ffmpeg", 100, 100, 30, Path("/tmp/o.mp4")))
    assert "-maxrate" not in uncapped


@pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg not installed")
def test_gif_size_cap_downscales_to_fit(tmp_path: Path) -> None:
    from flir_research_interface.analysis.media import MediaOptions, render_clip

    r = _make(tmp_path, n=20)
    big = render_clip(r, MediaOptions(start=0, stop=20, fmt="gif", scale=4))
    cap_mb = big["bytes"] * 0.4 / 1_000_000  # a cap well under the uncapped size
    small = render_clip(r, MediaOptions(start=0, stop=20, fmt="gif", scale=4, max_mb=cap_mb))
    assert small["bytes"] < big["bytes"], (small["bytes"], big["bytes"])
    assert small["bytes"] <= cap_mb * 1_000_000 * 1.3, small["bytes"]  # under the cap (± tolerance)
    assert small["width"] <= big["width"] and "downscaled" in (small["note"] or "")
