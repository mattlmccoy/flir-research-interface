"""Exported clips show the run's visible adjustment.

``VisibleSource`` applies the adjustment to each extracted RGB frame before warping and caching;
``media._visible_source`` passes the run's effective adjustment (sidecar, else recorded, else none).
The video clip here is synthetic (ffmpeg lavfi flat grey): grey 90 is far from both clip ends, so
doubling it (exposure +1 EV) is not clipped and equality with ``apply_adjust`` is meaningful.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from flir_research_interface.analysis import media, visible_overlay
from flir_research_interface.analysis.visible_adjust import apply_adjust
from flir_research_interface.analysis.visible_overlay import VisibleSource
from flir_research_interface.visible.recorder import FFMPEG_CANDIDATES
from flir_research_interface.visible.rtsp import find_ffprobe
from flir_research_interface.visible_adjust_store import write_sidecar

FFMPEG = find_ffprobe(FFMPEG_CANDIDATES)
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
W, H = 64, 48
_EV1 = {"exposure_ev": 1.0, "brightness": 0.0, "contrast": 1.0}
_NEUTRAL = {"exposure_ev": 0.0, "brightness": 0.0, "contrast": 1.0}


def _grey_run(root: Path) -> SimpleNamespace:
    """A reader-shaped object over a synthetic 2 s flat-grey (RGB 90) clip, identity alignment."""
    assert FFMPEG is not None
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", f"color=c=0x5a5a5a:size={W}x{H}:rate=10:duration=2", "-pix_fmt", "yuvj420p",
         "-c:v", "libx264", "-g", "5", str(root / "visible.mp4")],
        check=True,
    )  # fmt: skip
    return SimpleNamespace(
        path=root,
        host_t0_ns=None,
        visible={"file": "visible.mp4", "duration_s": 2.0, "measured_fps": 6.0,
                 "width": W, "height": H},
        metadata={"visible_alignment": {"H": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}},
    )


def _frame(reader: SimpleNamespace, adjust: dict[str, float] | None) -> np.ndarray:
    with VisibleSource(reader, FFMPEG, 1.0, 1.5, W, H, adjust=adjust) as src:
        frame = src.warped_at(1.2)
    assert frame is not None
    return frame


@needs_ffmpeg
def test_adjusted_frames_equal_apply_adjust_of_the_raw_frames(tmp_path: Path) -> None:
    reader = _grey_run(tmp_path)
    raw = _frame(reader, None)
    adjusted = _frame(reader, _EV1)
    assert 80 <= int(raw[H // 2, W // 2, 0]) <= 100  # sanity: the synthetic grey is ~90
    assert np.array_equal(adjusted, apply_adjust(raw, _EV1))
    assert int(adjusted[H // 2, W // 2, 0]) > int(raw[H // 2, W // 2, 0]) * 1.8  # about doubled


@needs_ffmpeg
def test_neutral_and_none_adjustment_return_identical_frames(tmp_path: Path) -> None:
    reader = _grey_run(tmp_path)
    raw = _frame(reader, None)
    assert np.array_equal(_frame(reader, _NEUTRAL), raw)


@needs_ffmpeg
def test_different_adjustments_give_different_frames(tmp_path: Path) -> None:
    """The warp cache lives on the source, so a new adjustment means a new source, never a stale
    frame."""
    reader = _grey_run(tmp_path)
    ev1 = _frame(reader, _EV1)
    ev_half = _frame(reader, {**_NEUTRAL, "exposure_ev": 0.5})
    assert not np.array_equal(ev1, ev_half)
    assert int(ev1[H // 2, W // 2, 0]) > int(ev_half[H // 2, W // 2, 0])


def _capture_source(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    class _Spy:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            seen.append(kwargs)

    monkeypatch.setattr(visible_overlay, "VisibleSource", _Spy)
    return seen


def _reader(run_dir: Path, metadata: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(path=run_dir, metadata=metadata)


def _call(reader: SimpleNamespace) -> None:
    opts = media.MediaOptions(visible_opacity=0.5)
    media._visible_source(reader, opts, "ffmpeg", 0.0, 1.0, W, H)


def test_media_passes_the_sidecar_adjustment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _capture_source(monkeypatch)
    write_sidecar(tmp_path, {"exposure_ev": 1.5, "brightness": 0.1, "contrast": 1.2})
    stamp = {"exposure_ev": -1.0, "brightness": 0.0, "contrast": 1.0, "preset": None,
             "based_on": None}
    _call(_reader(tmp_path, {"visible_adjust": stamp}))
    assert seen[0]["adjust"] == {"exposure_ev": 1.5, "brightness": 0.1, "contrast": 1.2}


def test_media_passes_the_recorded_adjustment_without_a_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _capture_source(monkeypatch)
    stamp = {"exposure_ev": -1.0, "brightness": 0.0, "contrast": 1.0, "preset": None,
             "based_on": None}
    _call(_reader(tmp_path, json.loads(json.dumps({"visible_adjust": stamp}))))
    assert seen[0]["adjust"] == {"exposure_ev": -1.0, "brightness": 0.0, "contrast": 1.0}


def test_media_passes_none_for_a_neutral_or_pre_feature_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _capture_source(monkeypatch)
    _call(_reader(tmp_path, {}))  # recorded before this feature: no stamp, no sidecar
    write_sidecar(tmp_path, _NEUTRAL)
    _call(_reader(tmp_path, {}))  # explicitly neutral
    assert [s["adjust"] for s in seen] == [None, None]
