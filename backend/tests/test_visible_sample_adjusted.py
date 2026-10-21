"""The visible-sample analysis on the adjusted video: a second, separate result.

``analyse_visible_sample(..., adjust=...)`` measures the luma after the operator's exposure /
brightness / contrast (``visible_adjust.apply_adjust``) and writes the ``visible_sample_adjusted``
file family; the raw analysis and its files are left alone, and the other way round. The clips are
the captured luma crops of the reference run pasted into a white frame and encoded lossless (see
tests/visible_sample_helpers.py), so the decoded values equal the captured ones and every expected
number below is worked out from the crops alone.
"""

from __future__ import annotations

import csv
import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from flir_research_interface import visible_adjust_store as vadj_store
from flir_research_interface.analysis import visible_sample_io as vio
from flir_research_interface.analysis import visible_sample_run as vsr
from flir_research_interface.analysis.visible_adjust import NEUTRAL, apply_adjust
from flir_research_interface.analysis.visible_sample import (
    frame_metrics,
    ir_to_visible_points,
    otsu_threshold,
    pick_rois,
    region_mask,
    roi_outline_ir,
)
from flir_research_interface.api.app import create_app
from tests import visible_sample_helpers as vh
from tests.visible_sample_helpers import (
    FFMPEG,
    FIXTURES,
    VIS_H,
    VIS_W,
    experiment,
    exported,
    lossless_clip,
    needs_ffmpeg,
    run_analysis,
)

# The shared fixture, bound here so that pytest finds it in this module (as test_visible_sample_run)
real = vh.real

DARKER = {"exposure_ev": -1.0, "brightness": 0.0, "contrast": 1.0}
RAW_FILES = [
    "visible_sample.csv", "visible_sample.json", "visible_sample_closeup.mp4",
    "visible_sample_plot.png",
]  # fmt: skip
ADJUSTED_FILES = [
    "visible_sample_adjusted.csv", "visible_sample_adjusted.json",
    "visible_sample_adjusted_closeup.mp4", "visible_sample_adjusted_plot.png",
]  # fmt: skip


# -- pure parts ---------------------------------------------------------------------------------


def test_frame_metrics_reads_the_bed_clipping_from_bed_luma() -> None:
    """The adjusted run measures adjusted luma but asks whether the *camera* clipped the bed."""
    luma = np.full((2, 4), 128, dtype=np.uint8)  # the adjusted frame: nothing at 255
    raw = np.full((2, 4), 255, dtype=np.uint8)
    raw[0, 0] = 200
    region = np.zeros((2, 4), dtype=bool)
    region[1, :2] = True
    bed = np.ones((2, 4), dtype=bool)
    m = frame_metrics(luma, None, region, 129, bed, bed_luma=raw)
    assert m.bed_clipped_frac == pytest.approx(7 / 8)
    assert m.sample_dark_px == 2 and m.sample_mean_luma == 128.0  # from luma, not raw
    assert frame_metrics(luma, None, region, 129, bed).bed_clipped_frac == 0.0  # default: luma


def test_family_names_and_what_each_family_owns() -> None:
    raw, adj = vio.family(None), vio.family(DARKER)
    assert (raw.json, raw.csv, raw.plot) == (
        "visible_sample.json", "visible_sample.csv", "visible_sample_plot.png"
    )  # fmt: skip
    assert (adj.json, adj.csv, adj.plot) == (
        "visible_sample_adjusted.json", "visible_sample_adjusted.csv",
        "visible_sample_adjusted_plot.png",
    )  # fmt: skip
    assert raw.closeup(0) == "visible_sample_closeup.mp4"
    assert adj.closeup(2) == "visible_sample_adjusted_closeup_002.mp4"
    for name in RAW_FILES + ["visible_sample_closeup_001.mp4", "visible_sample.csv.part"]:
        assert raw.owns(name) and not adj.owns(name), name
    for name in ADJUSTED_FILES + [
        "visible_sample_adjusted_closeup_001.mp4", "visible_sample_adjusted.json.part",
        "visible_sample_adjusted_closeup.mp4.part",
    ]:  # fmt: skip
        assert adj.owns(name) and not raw.owns(name), name
    for other in ("visible_full_range.mp4", "roi_series.csv", "visible_sample_notes.txt"):
        assert not raw.owns(other) and not adj.owns(other), other


def test_closeup_command_composes_the_adjustment_then_the_stretch() -> None:
    adjust = {"exposure_ev": -1.0, "brightness": 0.1, "contrast": 1.0}  # slope 0.5, intercept 0.1
    cmd = vsr._closeup_command(
        "ffmpeg", Path("in.mp4"), Path("out.part"), (320, 404, 126), 40.0, adjust
    )
    vf = cmd[cmd.index("-vf") + 1]
    assert "lutyuv=y='clip(((clip(0.5*val+(25.5),0,255))-40)*255/(250-40),0,255)'" in vf
    plain = vsr._closeup_command("ffmpeg", Path("in.mp4"), Path("out.part"), (320, 404, 126), 40.0)
    assert "lutyuv=y='clip((val-40)*255/(250-40),0,255)'" in plain[plain.index("-vf") + 1]


# -- the analysis on the real crops -------------------------------------------------------------


def _region(real: dict[str, Any]) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    sample, _ = pick_rois(real["rois"])
    assert sample is not None
    pts = ir_to_visible_points(roi_outline_ir(sample), real["visible_alignment"]["H"])
    out = region_mask(pts, 30)
    assert out is not None
    return out


@pytest.fixture(scope="module")
def crops() -> list[np.ndarray]:
    """The fixture's frames 3-26 (its first 5 s), with frames 0-2 (skipped) repeating frame 3."""
    npz = np.load(FIXTURES / "visible_sample_20261020_144402.npz")
    by_frame = {int(f): npz["crops"][i] for i, f in enumerate(npz["crop_frames"].tolist())}
    return [by_frame[max(i, 3)] for i in range(27)]


@pytest.fixture(scope="module")
def planes(real: dict[str, Any], crops: list[np.ndarray]) -> list[np.ndarray]:
    x0, y0, w, h = _region(real)[1]
    out = []
    for crop in crops:
        plane = np.full((VIS_H, VIS_W), 255, dtype=np.uint8)
        plane[y0 : y0 + h, x0 : x0 + w] = crop
        out.append(plane)
    return out


@pytest.fixture(scope="module")
def real_clip(tmp_path_factory: pytest.TempPathFactory, planes: list[np.ndarray]) -> Path:
    if FFMPEG is None:
        pytest.skip("ffmpeg not installed")
    return lossless_clip(tmp_path_factory.mktemp("adjusted") / "real.mp4", planes)


def _json(d: Path, name: str) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((d / "exports" / name).read_text())
    return doc


def _csv(d: Path, name: str) -> list[dict[str, str]]:
    with (d / "exports" / name).open(newline="") as fh:
        return list(csv.DictReader(fh))


@needs_ffmpeg
def test_neutral_adjust_gives_the_raw_result(
    tmp_path: Path, real: dict[str, Any], real_clip: Path
) -> None:
    """Every measured field is equal; only ``adjust`` and the ``files`` names differ."""
    d = experiment(tmp_path, real, [real_clip])
    raw = run_analysis(d)
    adj = run_analysis(d, adjust={**NEUTRAL, "source": "neutral"})
    assert raw["status"] == adj["status"] == "ok", (raw, adj)
    assert adj["adjust"] == {**NEUTRAL, "source": "neutral"}
    assert adj["files"] == [
        "visible_sample_adjusted.csv", "visible_sample_adjusted_closeup.mp4",
        "visible_sample_adjusted_plot.png", "visible_sample_adjusted.json",
    ]  # fmt: skip
    measured = {k: v for k, v in adj.items() if k not in ("adjust", "files")}
    assert measured == {k: v for k, v in raw.items() if k != "files"}
    assert "adjust" not in raw  # the raw result is unchanged in shape
    assert _csv(d, "visible_sample_adjusted.csv") == _csv(d, "visible_sample.csv")
    assert _json(d, "visible_sample_adjusted.json") == adj
    assert exported(d) == sorted(RAW_FILES + ADJUSTED_FILES)


def _decoded_first_frame(path: Path, side: int) -> np.ndarray:
    assert FFMPEG is not None
    raw = subprocess.run(
        [FFMPEG, "-v", "fatal", "-i", str(path), "-vf", "extractplanes=y",
         "-fps_mode", "passthrough", "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    first = np.frombuffer(raw, np.uint8).reshape(-1, 3 * side, 3 * side)[0].astype(float)
    return np.asarray(first.reshape(side, 3, side, 3).mean(axis=(1, 3)))


@needs_ffmpeg
def test_darker_adjust_changes_threshold_and_area_but_not_bed_clipping(
    tmp_path: Path, real: dict[str, Any], real_clip: Path, crops: list[np.ndarray],
    planes: list[np.ndarray],
) -> None:
    d = experiment(tmp_path, real, [real_clip])
    raw = run_analysis(d)
    adj = run_analysis(d, adjust={**DARKER, "source": "sidecar", "ignored": "x"})
    assert raw["status"] == adj["status"] == "ok", (raw, adj)
    assert adj["adjust"] == {**DARKER, "source": "sidecar"}
    mask = _region(real)[0]
    darker = [apply_adjust(c, DARKER)[mask] for c in crops[3:]]
    threshold = otsu_threshold(np.concatenate(darker))
    assert adj["threshold"] == threshold != raw["threshold"] == 178
    rows_raw, rows_adj = _csv(d, "visible_sample.csv"), _csv(d, "visible_sample_adjusted.csv")
    dark = [int(np.count_nonzero(px < threshold)) for px in darker]
    assert [int(r["sample_dark_px"]) for r in rows_adj] == dark
    assert dark != [int(r["sample_dark_px"]) for r in rows_raw]
    # the camera clipped the bed whatever the operator's sliders say (255 -> 128 at -1 EV)
    assert [r["bed_clipped_frac"] for r in rows_adj] == [r["bed_clipped_frac"] for r in rows_raw]
    assert 0.0 < float(rows_adj[1]["bed_clipped_frac"]) < 1.0
    # the close-up is the adjusted crop, stretched from the adjusted black level
    dark_px = np.concatenate([px[px < threshold] for px in darker])
    lo = round(min(float(np.percentile(dark_px, 1)), 249.0), 2)
    assert adj["stretch"] == {"lo": lo, "hi": 250} != raw["stretch"]
    box = adj["bbox"]
    x, y, side = vsr._closeup_box((box["x0"], box["y0"], box["w"], box["h"]), (VIS_W, VIS_H))
    source = apply_adjust(planes[3][y : y + side, x : x + side], DARKER).astype(float)
    expected = np.clip((source - lo) * 255 / (250 - lo), 0, 255)
    shrunk = _decoded_first_frame(d / "exports" / "visible_sample_adjusted_closeup.mp4", side)
    assert np.abs(shrunk - expected).mean() < 2.0
    assert expected.min() < 60 and expected.max() > 100  # neither a no-op nor all black


def _plant_parts(d: Path) -> None:
    for name in ("visible_sample.csv.part", "visible_sample_adjusted.csv.part"):
        (d / "exports" / name).write_text("half")


@needs_ffmpeg
def test_neither_family_deletes_the_other(
    tmp_path: Path, real: dict[str, Any], real_clip: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling P2: an ok, skipped or failed run of one family leaves the other's files (results and
    half-written ``.part``) alone; it still removes its own stale ones."""
    d = experiment(tmp_path, real, [real_clip])
    assert run_analysis(d)["status"] == "ok"
    assert run_analysis(d, adjust=DARKER)["status"] == "ok"
    exports = d / "exports"
    adj_before = {n: (exports / n).read_bytes() for n in ADJUSTED_FILES}
    _plant_parts(d)
    assert run_analysis(d)["status"] == "ok"  # raw again
    assert {n: (exports / n).read_bytes() for n in ADJUSTED_FILES} == adj_before
    assert exported(d) == sorted(RAW_FILES + ADJUSTED_FILES + ["visible_sample_adjusted.csv.part"])
    _plant_parts(d)
    assert run_analysis(d, ffmpeg="/no/such/ffmpeg")["status"] == "skipped"
    assert exported(d) == sorted(
        ["visible_sample.json"] + ADJUSTED_FILES + ["visible_sample_adjusted.csv.part"]
    )
    assert {n: (exports / n).read_bytes() for n in ADJUSTED_FILES} == adj_before

    def fails(*_a: Any, **_kw: Any) -> None:
        raise RuntimeError("encoder died")

    with monkeypatch.context() as m:
        m.setattr(vsr, "_encode_closeup", fails)
        assert run_analysis(d)["status"] == "failed"
    assert {n: (exports / n).read_bytes() for n in ADJUSTED_FILES} == adj_before

    # and the other way round: the raw result survives every adjusted outcome
    assert run_analysis(d)["status"] == "ok"
    raw_before = {n: (exports / n).read_bytes() for n in RAW_FILES}
    _plant_parts(d)
    assert run_analysis(d, adjust=DARKER)["status"] == "ok"
    assert exported(d) == sorted(RAW_FILES + ADJUSTED_FILES + ["visible_sample.csv.part"])
    _plant_parts(d)
    assert run_analysis(d, adjust=DARKER, ffmpeg="/no/such/ffmpeg")["status"] == "skipped"
    with monkeypatch.context() as m:
        m.setattr(vsr, "_encode_closeup", fails)
        assert run_analysis(d, adjust=DARKER)["status"] == "failed"
    left = RAW_FILES + ["visible_sample_adjusted.json", "visible_sample.csv.part"]
    assert exported(d) == sorted(left)
    assert {n: (exports / n).read_bytes() for n in RAW_FILES} == raw_before


@needs_ffmpeg
def test_stopped_adjusted_run_says_which_adjustment_and_invalid_one_fails(
    tmp_path: Path, real: dict[str, Any], real_clip: Path
) -> None:
    d = experiment(tmp_path, real, [real_clip])
    out = run_analysis(d, adjust={**DARKER, "source": "recorded"}, ffmpeg="/no/such/ffmpeg")
    assert out["status"] == "skipped" and out["adjust"] == {**DARKER, "source": "recorded"}
    assert out["files"] == ["visible_sample_adjusted.json"]
    bad = run_analysis(d, adjust={**DARKER, "exposure_ev": 9.0})
    assert bad["status"] == "failed" and bad["reason"].startswith("ValueError: exposure_ev")
    assert bad["adjust"] is None
    assert exported(d) == ["visible_sample_adjusted.json"]  # the raw analysis never ran


# -- the app ------------------------------------------------------------------------------------


def _wait_derived(c: TestClient, name: str, timeout: float = 120.0) -> dict[str, Any]:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        job: dict[str, Any] = c.get(f"/api/experiments/{name}/export/derived/status").json()
        if job["state"] in ("done", "error"):
            return job
        time.sleep(0.05)
    raise AssertionError("derived job did not finish in time")


def _app(root: Path) -> Any:
    return create_app(
        default_backend="simulated", sim_fps=60.0, experiments_root=root, min_free_gb=0.0
    )


@needs_ffmpeg
def test_derived_route_with_visible_adjusted_writes_both_families(
    tmp_path: Path, real: dict[str, Any], real_clip: Path
) -> None:
    d = experiment(tmp_path, real, [real_clip])
    vadj_store.write_sidecar(d, DARKER)
    with TestClient(_app(tmp_path)) as c:
        info = c.get(f"/api/experiments/{d.name}").json()
        assert info["visible_sample_adjusted"] is None
        r = c.post(f"/api/experiments/{d.name}/export/derived?video=false&visible_adjusted=true")
        assert r.status_code == 200
        job = _wait_derived(c, d.name)
        assert job["state"] == "done", job
        assert job["visible_adjusted"] == {"status": "ok", "reason": None}
        info = c.get(f"/api/experiments/{d.name}").json()
    assert info["visible_sample"]["status"] == "ok" and "adjust" not in info["visible_sample"]
    adj = info["visible_sample_adjusted"]
    assert adj == _json(d, "visible_sample_adjusted.json")
    assert adj["status"] == "ok" and adj["adjust"] == {**DARKER, "source": "sidecar"}
    assert set(RAW_FILES + ADJUSTED_FILES) <= set(exported(d))


def test_derived_route_without_the_flag_runs_raw_only_and_adjusted_failure_is_separate(
    tmp_path: Path, real: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The adjusted run reports its own status; its failure never fails the raw run or the job."""
    seen: list[Any] = []

    def fake(reader: Any, ffmpeg: Any = None, ffprobe: Any = None, closeup: bool = True,
             adjust: Any = None) -> dict[str, Any]:
        seen.append(adjust)
        if adjust is not None:
            raise RuntimeError("adjusted exploded")
        return {"status": "ok", "reason": None, "files": ["visible_sample.json"]}

    monkeypatch.setattr(vsr, "analyse_visible_sample", fake)
    d = experiment(tmp_path, real)
    with TestClient(_app(tmp_path)) as c:
        c.post(f"/api/experiments/{d.name}/export/derived?video=false")
        job = _wait_derived(c, d.name)
        assert job["state"] == "done" and job["visible_adjusted"] is None, job
        assert seen == [None]
        c.post(f"/api/experiments/{d.name}/export/derived?video=false&visible_adjusted=true")
        job = _wait_derived(c, d.name)
    assert job["state"] == "done", job
    reason = "RuntimeError: adjusted exploded"
    assert job["visible_adjusted"] == {"status": "failed", "reason": reason}
    assert seen == [None, None, {**NEUTRAL, "source": "neutral"}]  # raw first, then adjusted


@needs_ffmpeg
def test_a_stale_cleanup_error_after_commit_keeps_the_result(
    tmp_path: Path, real: dict[str, Any], real_clip: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The result is already in place when the old files are removed: failing to remove them must
    not send a good result into the failure path, which would delete it."""

    def broken(*_a: Any, **_kw: Any) -> None:
        raise OSError("exports went away")

    d = experiment(tmp_path, real, [real_clip])
    monkeypatch.setattr(vsr, "_remove_stale", broken)
    out = run_analysis(d, adjust=DARKER, closeup=False)
    assert out["status"] == "ok", out
    assert set(out["files"]) <= set(exported(d))
    assert _json(d, "visible_sample_adjusted.json") == out


class _Blocking:
    """A stub analysis that holds the derived job in its raw step until ``release``."""

    def __init__(self) -> None:
        self.entered, self.go = threading.Event(), threading.Event()

    def __call__(self, reader: Any, ffmpeg: Any = None, ffprobe: Any = None,
                 closeup: bool = True, adjust: Any = None) -> dict[str, Any]:
        if adjust is None:
            self.entered.set()
            assert self.go.wait(30)
        return {"status": "ok", "reason": None, "files": []}


@pytest.mark.parametrize("first_flag", [False, True])
def test_an_adjusted_request_while_a_regenerate_runs(
    tmp_path: Path, real: dict[str, Any], monkeypatch: pytest.MonkeyPatch, first_flag: bool
) -> None:
    """A running job without the adjusted analysis refuses an adjusted request (409) rather than
    dropping it silently; one that already includes it is returned as it is."""
    stub = _Blocking()
    monkeypatch.setattr(vsr, "analyse_visible_sample", stub)
    d = experiment(tmp_path, real)
    base = f"/api/experiments/{d.name}/export/derived?video=false"
    with TestClient(_app(tmp_path)) as c:
        try:
            first = c.post(base + ("&visible_adjusted=true" if first_flag else ""))
            assert first.status_code == 200 and first.json()["state"] == "running"
            assert stub.entered.wait(30)
            again = c.post(base + "&visible_adjusted=true")
            if first_flag:
                assert again.status_code == 200 and again.json()["state"] == "running"
                assert again.json()["visible_adjusted_requested"] is True
            else:
                assert again.status_code == 409
                assert again.json()["detail"] == (
                    "a derived regenerate without the adjusted analysis is running; "
                    "retry when it is done"
                )
            assert c.post(base).status_code == 200  # a raw-only request is still deduplicated
        finally:
            stub.go.set()
        job = _wait_derived(c, d.name)
    assert job["state"] == "done", job
    assert (job["visible_adjusted"] is not None) == first_flag
