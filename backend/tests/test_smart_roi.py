"""Smart ROI spec parsing, detection and tracking."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from flir_research_interface.analysis.series import parse_rois, roi_index
from flir_research_interface.analysis.smart_roi import (
    HOLD_S,
    SmartResult,
    SmartRoiSpec,
    SmartTracker,
    parse_smart_roi,
)
from flir_research_interface.radiometry.emissivity import Radiometry, recorrect_celsius

SEARCH = [[0, 0], [40, 0], [40, 30]]


def _raw(**kw: Any) -> dict[str, Any]:
    return {"id": 3, "kind": "smart", "search": SEARCH, **kw}


def test_parse_smart_defaults() -> None:
    spec = parse_smart_roi(_raw())
    assert isinstance(spec, SmartRoiSpec)
    assert spec.id == 3 and spec.name is None
    assert spec.search == ((0, 0), (40, 0), (40, 30))
    assert spec.rings_px == (5, 10, 25)
    assert spec.rule == "relative" and spec.fixed_c is None
    assert spec.sensitivity == 0.5 and spec.ring_emissivity is None


def test_parse_smart_full() -> None:
    spec = parse_smart_roi(
        _raw(name="pad", rings_px=[2, 4], rule="fixed", fixed_c=80, sensitivity=0.3,
             ring_emissivity=0.9)
    )
    assert (spec.name, spec.rings_px, spec.rule, spec.fixed_c) == ("pad", (2, 4), "fixed", 80.0)
    assert spec.sensitivity == 0.3 and spec.ring_emissivity == 0.9


@pytest.mark.parametrize(
    "bad",
    [
        {"search": [[0, 0], [1, 1]]},
        {"search": [[0, 0], [1, 1], [1]]},
        {"rings_px": [5, 5]},
        {"rings_px": [10, 5]},
        {"rings_px": [0, 5]},
        {"rings_px": [1.5, 5]},
        {"rings_px": []},
        {"rule": "fixed"},
        {"rule": "bogus"},
        {"sensitivity": 0.2},
        {"sensitivity": 0.8},
        {"ring_emissivity": 0},
        {"rings_px": [5, 10, 101]},  # over MAX_RING_PX: would stall the camera thread
        {"rule": "fixed", "fixed_c": float("nan")},
        {"rule": "fixed", "fixed_c": float("inf")},
        {"fixed_c": float("-inf")},
        {"ring_emissivity": float("nan")},
    ],
)
def test_parse_smart_rejects(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        parse_smart_roi(_raw(**bad))


def test_parse_smart_ring_limit_is_inclusive() -> None:
    from flir_research_interface.analysis.smart_spec import MAX_RING_PX

    assert MAX_RING_PX == 100
    assert parse_smart_roi(_raw(rings_px=[5, 10, 100])).rings_px == (5, 10, 100)
    with pytest.raises(ValueError, match="100"):
        parse_smart_roi(_raw(rings_px=[101]))


def test_parse_rois_passes_smart_through() -> None:
    out = parse_rois(json.dumps([_raw(name="pad", emissivity=0.8)]))
    assert out == [
        {
            "id": 3, "kind": "smart", "name": "pad", "search": [[0, 0], [40, 0], [40, 30]],
            "rings_px": [5, 10, 25], "rule": "relative", "fixed_c": None,
            "sensitivity": 0.5, "ring_emissivity": None, "emissivity": 0.8,
        }
    ]


def test_roi_index_refuses_smart() -> None:
    roi = parse_rois(json.dumps([_raw()]))[0]
    with pytest.raises(ValueError, match="smart ROIs have no static pixels"):
        roi_index(roi, 100, 100)


# --- detector / tracker -------------------------------------------------------------------------

W, H = 640, 480
BOX = ((100, 100), (300, 100), (300, 260), (100, 260))  # user's drawn search outline
CX, CY, RX, RY = 200.0, 180.0, 30.0, 20.0
FIXTURE = Path(__file__).parent / "fixtures" / "smart_roi_20261020.npz"


def _spec(**kw: Any) -> SmartRoiSpec:
    return SmartRoiSpec(id=1, name="s", search=BOX, **kw)


def _rho(cx: float = CX, cy: float = CY, rx: float = RX, ry: float = RY) -> np.ndarray:
    ys, xs = np.mgrid[0:H, 0:W]
    return np.sqrt(((xs - cx) / rx) ** 2 + ((ys - cy) / ry) ** 2)


def _blob(scale: float = 1.0, cx: float = CX, cy: float = CY) -> np.ndarray:
    """600 °C ellipse; outside it the powder falls from 240 °C to 40 °C with distance."""
    rho = _rho(cx, cy, RX * scale, RY * scale)
    d = np.maximum(rho - 1.0, 0.0) * RY * scale  # rough px distance from the ellipse
    out = 40.0 + 200.0 * np.exp(-d / 8.0)
    return np.where(rho <= 1.0, 600.0, out)


def _ellipse_px(scale: float = 1.0) -> int:
    return int((_rho(rx=RX * scale, ry=RY * scale) <= 1.0).sum())


def test_cold_frame_stays_searching() -> None:
    r = SmartTracker(_spec(), W, H).update(np.full((H, W), 22.0), 0.0)
    assert isinstance(r, SmartResult)
    assert r.state == "searching" and r.valid is False
    assert r.sample["mean_c"] is None and r.dims is None and r.labels is None


def test_locks_and_measures_synthetic_blob() -> None:
    r = SmartTracker(_spec(), W, H).update(_blob(), 0.0)
    assert r.state == "locked" and r.valid is True and r.over_range is False
    assert r.dims is not None and r.dims["units"] == "px"
    assert abs(r.dims["area_px"] - _ellipse_px()) <= 0.03 * _ellipse_px()
    assert r.sample["mean_c"] == 600.0
    assert [(g["inner_px"], g["outer_px"]) for g in r.rings] == [(0, 5), (5, 10), (10, 25)]
    means = [g["mean_c"] for g in r.rings]
    assert all(a > b for a, b in zip(means, means[1:], strict=False))
    assert abs(r.dims["length_px"] - 2 * RX - 1) <= 2 and abs(r.dims["width_px"] - 2 * RY - 1) <= 2
    assert abs(r.dims["centroid_x"] - CX) < 0.5 and abs(r.dims["centroid_y"] - CY) < 0.5
    assert r.dims["area_change_pct"] == 0.0
    # labels: crop of bbox with 1 = sample, 2.. = rings
    assert r.bbox is not None and r.labels is not None and r.labels.dtype == np.uint8
    x0, y0, x1, y1 = r.bbox
    assert r.labels.shape == (y1 - y0, x1 - x0)
    assert int((r.labels == 1).sum()) == r.dims["area_px"]
    assert set(np.unique(r.labels).tolist()) == {0, 1, 2, 3, 4}


def test_tracks_growth_and_change_pct() -> None:
    t = SmartTracker(_spec(), W, H)
    t.update(_blob(), 0.0)
    r = t.update(_blob(1.09), 1 / 30)
    assert r.state == "locked" and r.dims is not None
    assert abs(r.dims["area_change_pct"] - 18.8) <= 2
    assert abs(r.dims["length_change_pct"] - 9.0) <= 3


def test_hot_neighbour_not_adopted() -> None:
    t = SmartTracker(_spec(), W, H)
    first = t.update(_blob(), 0.0)
    frame = _blob()
    hot = _rho(CX + RX + 18, CY, 4.0, 4.0) <= 1.0  # a hotter spot 14 px right of the sample
    frame[hot] = 900.0
    r = t.update(frame, 1 / 30)
    assert r.state == "locked" and r.dims is not None and first.dims is not None
    assert abs(r.dims["centroid_x"] - first.dims["centroid_x"]) < 3
    assert abs(r.dims["centroid_y"] - first.dims["centroid_y"]) < 3


def test_bad_frame_holds_then_searches() -> None:
    t = SmartTracker(_spec(), W, H)
    first = t.update(_blob(), 0.0)
    flat = np.full((H, W), 40.0)
    flat[::2] += 1.0  # contrast 1 °C < MIN_CONTRAST_C
    held = t.update(flat, 0.1)
    assert held.state == "holding" and held.valid is True
    assert held.bbox == first.bbox and held.dims is not None and first.dims is not None
    geometry = ("area_px", "length_px", "width_px", "centroid_x", "centroid_y", "perimeter_px")
    assert all(held.dims[k] == first.dims[k] for k in geometry)  # the last good outline
    assert held.sample["mean_c"] is not None and held.sample["mean_c"] < 50
    gone = t.update(flat, 0.1 + HOLD_S + 0.1)
    assert gone.state == "searching" and gone.valid is False


def test_relocks_in_drawn_outline_after_tracking_far_outside_it() -> None:
    """Tracked (uncapped) far from the drawn outline, then lost: the re-lock search area (last
    outline ∩ capped user outline) is empty, so it falls back to the drawn outline."""
    t = SmartTracker(_spec(), W, H)
    t.update(_blob(), 0.0)
    ts = 0.0
    for cx in range(int(CX) + 8, 441, 8):  # walk the sample far right of BOX (x <= 300)
        ts += 1 / 30
        r = t.update(_blob(cx=cx), ts)
        assert r.state == "locked", cx
    assert r.dims is not None and r.dims["centroid_x"] > 420
    flat = np.full((H, W), 40.0)
    gone = t.update(flat, ts + HOLD_S + 0.1)
    assert gone.state == "searching"
    back = t.update(_blob(), ts + HOLD_S + 0.2)  # the sample is back where the user drew
    assert back.state == "locked" and back.dims is not None
    assert abs(back.dims["centroid_x"] - CX) < 0.5


def test_runaway_hot_spot_does_not_shrink_the_outline() -> None:
    """A smoking/arcing spot (a few px far hotter than the sample) must not set the edge: the hot
    level is the region's p90, so the area stays within 10 % of the no-hotspot area while max_c
    still reports the spot."""
    clean = SmartTracker(_spec(), W, H).update(_blob(), 0.0)
    frame = _blob()
    frame[int(CY) - 2 : int(CY) + 3, int(CX) - 2 : int(CX) + 3] = 3000.0  # 25 px runaway spot
    hot = SmartTracker(_spec(), W, H).update(frame, 0.0)
    assert clean.dims is not None and hot.dims is not None
    assert hot.state == "locked"
    assert abs(hot.dims["area_px"] / clean.dims["area_px"] - 1.0) <= 0.10, (
        hot.dims["area_px"], clean.dims["area_px"])
    assert hot.sample["max_c"] == 3000.0


def test_over_range_core() -> None:
    frame = _blob()
    core = _rho(rx=RX / 2, ry=RY / 2) <= 1.0
    frame[core] = -60.0  # wrapped reading
    r = SmartTracker(_spec(), W, H).update(frame, 0.0, over=core)
    assert r.bbox is not None and r.dims is not None
    assert abs(r.dims["area_px"] - _ellipse_px()) <= 0.03 * _ellipse_px()
    assert r.over_range is True and r.valid is False
    assert r.sample["mean_c"] is None


def test_fixed_rule_uses_isotherm() -> None:
    rr = _rho(rx=12.0, ry=12.0)
    frame = 40.0 + 560.0 * np.exp(-(rr**2))  # 600 °C core, smooth Gaussian falloff
    r = SmartTracker(_spec(rule="fixed", fixed_c=300.0), W, H).update(frame, 0.0)
    want = int((frame >= 300.0).sum())
    assert r.state == "locked" and r.dims is not None and r.edge_level_c == 300.0
    assert abs(r.dims["area_px"] - want) <= 0.02 * want


def test_baseline_survives_relock() -> None:
    t = SmartTracker(_spec(), W, H)
    t.update(_blob(), 0.0)
    cold = np.full((H, W), 40.0)
    for i in range(60):
        r = t.update(cold, 0.1 + i / 30)
    assert r.state == "searching"
    r = t.update(_blob(1.09), 2.5)
    assert r.state == "locked" and r.dims is not None
    assert abs(r.dims["area_change_pct"] - 18.8) <= 2  # vs the first lock, not the re-lock


def test_ring_emissivity_recorrects_rings_only() -> None:
    rbf = Radiometry(22474.88, 1520.0, 1.05)
    cam = {
        "calibration_constants": {"R": rbf.R, "B": rbf.B, "F": rbf.F},
        "object_parameters": {"ObjectEmissivity": 0.95, "ReflectedTemperature": 293.15},
    }
    plain = SmartTracker(_spec(), W, H, cam=cam).update(_blob(), 0.0)
    eps = SmartTracker(_spec(ring_emissivity=0.5), W, H, cam=cam).update(_blob(), 0.0)
    assert eps.sample == plain.sample and eps.dims == plain.dims
    want = recorrect_celsius(
        plain.rings[0]["max_c"], rbf, eps_cam=0.95, trefl_cam_k=293.15, eps=0.5, trefl_k=293.15
    )
    assert abs(eps.rings[0]["max_c"] - float(want)) < 1e-6
    assert eps.rings[0]["mean_c"] > plain.rings[0]["mean_c"]


def test_update_is_fast() -> None:
    t = SmartTracker(_spec(), W, H)
    frame = _blob()
    t.update(frame, 0.0)
    n = 50
    t0 = time.perf_counter()
    for i in range(n):
        r = t.update(frame, (i + 1) / 30)
    avg_ms = (time.perf_counter() - t0) / n * 1000
    assert r.state == "locked"
    print(f"smart ROI update: {avg_ms:.2f} ms/frame")
    assert avg_ms < 5.0


def test_fixture_20261020_locks_after_heating() -> None:
    """Real frames of 20261020_144402_Run (graphite cube in PA12), cropped round freehand_sample."""
    fx = np.load(FIXTURE)
    frames, origin, t_s = fx["celsius"], fx["origin"], fx["t_s"]
    search = tuple((int(x - origin[0]), int(y - origin[1])) for x, y in fx["polygon"])
    h, w = frames.shape[1:]
    t = SmartTracker(SmartRoiSpec(id=1, name="cube", search=search), w, h)
    res = [t.update(f.astype(np.float64), float(ts)) for f, ts in zip(frames, t_s, strict=True)]
    for ts, r in zip(t_s, res, strict=True):
        a = None if r.dims is None else r.dims["area_px"]
        print(f"t={ts:7.1f}s state={r.state} area={a} edge={r.edge_level_c}")
    assert res[0].state == "searching" and res[0].valid is False
    at274, at604 = res[2], res[4]
    assert at274.state == "locked" and at274.dims is not None
    assert 400 <= at274.dims["area_px"] <= 1200
    assert at604.state == "locked" and at604.dims is not None
    assert at604.dims["area_px"] < at274.dims["area_px"]



def test_fixture_20261020_track_is_stable() -> None:
    """A still frame must give the same outline on the lock frame and every frame after it: the
    lock is measured in the same (outline + margin) area the tracker searches next frame."""
    fx = np.load(FIXTURE)
    origin = fx["origin"]
    search = tuple((int(x - origin[0]), int(y - origin[1])) for x, y in fx["polygon"])
    h, w = fx["celsius"].shape[1:]
    for k in (2, 3, 4):
        t = SmartTracker(SmartRoiSpec(id=1, name="cube", search=search), w, h)
        frame = fx["celsius"][k].astype(np.float64)
        res = [t.update(frame, i / 30) for i in range(4)]  # the lock frame and 3 more
        assert all(r.state == "locked" for r in res), [r.state for r in res]
        areas = [r.dims["area_px"] for r in res if r.dims is not None]
        assert max(areas) - min(areas) <= 0.03 * areas[0], areas
        assert res[-1].dims is not None and abs(res[-1].dims["area_change_pct"]) <= 3


def _gauss_blob() -> np.ndarray:
    """600 °C core with a smooth falloff, so the outline depends on the edge level."""
    return 40.0 + 560.0 * np.exp(-(_rho() ** 2))


def _box(hw: int, hh: int) -> tuple[tuple[int, int], ...]:
    x0, x1, y0, y1 = int(CX) - hw, int(CX) + hw, int(CY) - hh, int(CY) + hh
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))


def test_outline_does_not_depend_on_search_area_size() -> None:
    areas = []
    for hw, hh in ((45, 32), (90, 64)):  # tight drawn outline, and one twice the size
        t = SmartTracker(SmartRoiSpec(id=1, name=None, search=_box(hw, hh)), W, H)
        res = [t.update(_gauss_blob(), i / 30) for i in range(2)]
        assert all(r.state == "locked" for r in res), [r.state for r in res]
        assert res[-1].dims is not None
        areas.append(res[-1].dims["area_px"])
    assert abs(areas[0] - areas[1]) <= 0.03 * max(areas), areas


def test_sample_clipped_by_frame_edge_stays_locked() -> None:
    frame = _blob(cx=10.0)  # the left third of the ellipse is outside the image
    box = ((0, 100), (120, 100), (120, 260), (0, 260))
    t = SmartTracker(SmartRoiSpec(id=1, name=None, search=box), W, H)
    res = [t.update(frame, i / 30) for i in range(3)]
    assert all(r.state == "locked" for r in res), [r.state for r in res]
    want = int(((_rho(cx=10.0) <= 1.0)).sum())
    assert res[-1].dims is not None and abs(res[-1].dims["area_px"] - want) <= 0.03 * want


def test_failed_refinement_keeps_previous_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """If re-measuring the lock frame with the band rule fails, the previous pass stands."""
    calls: list[int] = []
    real = SmartTracker._detect

    def detect(self: SmartTracker, *a: Any) -> Any:
        calls.append(1)
        out = real(self, *a)
        return (None, out[1]) if len(calls) == 2 else out

    monkeypatch.setattr(SmartTracker, "_detect", detect)
    t = SmartTracker(_spec(), W, H)
    r = t.update(_blob(), 0.0)
    assert len(calls) == 2
    assert r.state == "locked" and r.valid is True and r.dims is not None
    r2 = t.update(_blob(1.09), 1 / 30)  # the area-jump check still runs against that lock
    assert r2.state == "locked" and r2.dims is not None
    assert abs(r2.dims["area_change_pct"] - 18.8) <= 2


@pytest.mark.parametrize("spot_c", [700.0, 900.0])
def test_hot_neighbour_does_not_move_gaussian_edge(spot_c: float) -> None:
    """A hotter spot ~26 px off a smooth sample's edge must not change the sample's edge level:
    ``hot`` comes from the chosen region, not from everything in the search area."""
    t = SmartTracker(_spec(), W, H)
    first = t.update(_gauss_blob(), 0.0)
    assert first.state == "locked" and first.dims is not None
    frame = _gauss_blob()
    frame[_rho(CX + 51, CY, 4.0, 4.0) <= 1.0] = spot_c  # sample edge is at ~CX+25
    res = [t.update(frame, (i + 1) / 30) for i in range(5)]
    assert all(r.state == "locked" for r in res), [r.state for r in res]
    for r in res:
        assert r.dims is not None
        assert abs(r.dims["area_px"] - first.dims["area_px"]) <= 0.03 * first.dims["area_px"]
        assert abs(r.dims["centroid_x"] - first.dims["centroid_x"]) < 1


# --- label wire format ---------------------------------------------------------------------------

KNOWN_CROP = np.array([[0, 1, 1, 0], [1, 1, 1, 2], [2, 2, 2, 2]], dtype=np.uint8)
KNOWN_VECTOR = "AAEAAAABAgAAAAABAAAAAQMAAAACBQAAAA=="  # runs (0,1)(1,2)(0,1)(1,3)(2,5)


def _ref_decode(b64: str, w: int, h: int) -> np.ndarray:
    import base64
    import struct

    raw = base64.b64decode(b64)
    flat: list[int] = []
    for i in range(0, len(raw), 5):
        value, run = struct.unpack_from("<BI", raw, i)
        flat += [value] * run
    return np.array(flat, dtype=np.uint8).reshape(h, w)


def test_encode_round_trip() -> None:
    from flir_research_interface.analysis.smart_wire import encode_labels

    rng = np.random.default_rng(7)
    crop = rng.integers(0, 5, size=(5, 7)).astype(np.uint8)
    crop[2, :] = 1  # a long run too
    assert np.array_equal(_ref_decode(encode_labels(crop), 7, 5), crop)


def test_encode_known_vector() -> None:
    from flir_research_interface.analysis.smart_wire import encode_labels

    assert encode_labels(KNOWN_CROP) == KNOWN_VECTOR


def test_smart_overlay_shape() -> None:
    from flir_research_interface.analysis.smart_wire import smart_overlay

    res = SmartResult(state="locked", valid=True, bbox=(2, 3, 6, 6), labels=KNOWN_CROP)
    assert smart_overlay(res, 4) == {
        "id": 4,
        "state": "locked",
        "valid": True,
        "bbox": [2, 3, 6, 6],
        "labels": KNOWN_VECTOR,
    }
    off = smart_overlay(SmartResult(state="searching", valid=False), 4)
    assert off["bbox"] is None and off["labels"] is None and off["valid"] is False
