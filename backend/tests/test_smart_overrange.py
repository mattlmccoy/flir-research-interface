"""Smart ROI readouts while some pixels are over range (lower-bound mean, exact min, max > range).

The TC-POWER feed (``live_roi_payload``) must stay unchanged: an over-range smart ROI is
``valid=False`` with null temperatures. The bounded numbers ride a separate, UI-only channel
(``SmartResult.over_stats`` -> ``smart_overlay(...)["over"]``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from flir_research_interface.analysis.live_temps import live_roi_payload
from flir_research_interface.analysis.smart_roi import SmartRoiSpec, SmartTracker
from flir_research_interface.analysis.smart_wire import smart_overlay
from flir_research_interface.radiometry.emissivity import Radiometry, recorrect_celsius
from flir_research_interface.radiometry.overrange import over_range_mask
from flir_research_interface.radiometry.temperature_linear import IRFormat, counts_to_celsius

FIXTURE = Path(__file__).parent / "fixtures" / "smart_overrange_20261020.npz"
W, H = 640, 480
BOX = ((100, 100), (300, 100), (300, 260), (100, 260))
CX, CY, RX, RY = 200.0, 180.0, 30.0, 20.0
STAT_KEYS = {"mean_lb_c", "min_c", "min_is_bound", "max_c", "over_px", "ceiling_c"}


def _rho(cx: float = CX, cy: float = CY, rx: float = RX, ry: float = RY) -> np.ndarray:
    ys, xs = np.mgrid[0:H, 0:W]
    return np.sqrt(((xs - cx) / rx) ** 2 + ((ys - cy) / ry) ** 2)


def _blob() -> np.ndarray:
    """200 °C ellipse with a 180..240 °C gradient inside; powder falls to 40 °C outside it."""
    rho = _rho()
    d = np.maximum(rho - 1.0, 0.0) * RY
    out = 40.0 + 100.0 * np.exp(-d / 8.0)
    return np.where(rho <= 1.0, 240.0 - 60.0 * rho, out)


def _spec(**kw: Any) -> SmartRoiSpec:
    return SmartRoiSpec(id=1, name="s", search=BOX, **kw)


def _real() -> tuple[list[np.ndarray], list[np.ndarray | None], SmartRoiSpec, float]:
    fx = np.load(FIXTURE)
    fmt = IRFormat(str(fx["ir_format"]))
    ox, oy = (int(v) for v in fx["origin"])
    search = tuple((int(x) - ox, int(y) - oy) for x, y in fx["polygon"])
    spec = SmartRoiSpec(id=113, name="cube", search=search,
                        rings_px=tuple(int(r) for r in fx["rings_px"]))
    celsius = [counts_to_celsius(c, fmt) for c in fx["counts"]]
    over = [over_range_mask(c) for c in fx["counts"]]
    return celsius, over, spec, float(fx["high_c"])


def _track_real(ceiling: float | None) -> list[Any]:
    celsius, over, spec, _ = _real()
    h, w = celsius[0].shape
    t = SmartTracker(spec, w, h)
    return [t.update(c, i / 30, o, ceiling_c=ceiling)
            for i, (c, o) in enumerate(zip(celsius, over, strict=True))]


def _sample_vals(r: Any, celsius: np.ndarray, over: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(sample °C, sample over-range mask) at the result's sample pixels (labels == 1)."""
    x0, y0, x1, y1 = r.bbox
    m = r.labels == 1
    return celsius[y0:y1, x0:x1][m], over[y0:y1, x0:x1][m]


# --- tracker --------------------------------------------------------------------------------------


def test_real_overrange_frame_bounds_mean_and_keeps_exact_min() -> None:
    """Real 20261020 frame 18820 (626.7 s): six sample pixels wrapped to ~-80 °C. The mean counts
    them at the 250 °C ceiling (a lower bound) and the min ignores them (exact)."""
    celsius, over, _, high = _real()
    res = _track_real(high)
    r = res[3]
    assert r.state == "locked" and r.over_range is True and r.valid is False
    assert r.sample == {"mean_c": None, "max_c": None, "min_c": None}  # the feed's view: unchanged
    assert over[3] is not None
    vals, sat = _sample_vals(r, celsius[3], over[3])
    assert int(sat.sum()) == 6 and float(vals[sat].max()) < -50  # the wrapped readings are cold
    s = r.over_stats["sample"]
    assert set(s) == STAT_KEYS
    assert s["over_px"] == 6 and s["ceiling_c"] == high
    good = vals[~sat]
    want = (good.sum() + 6 * high) / vals.size
    assert abs(s["mean_lb_c"] - want) < 1e-9
    assert s["mean_lb_c"] > good.mean()  # counting them at the ceiling only raises the mean
    assert s["min_c"] == float(good.min()) and s["min_c"] > 100.0
    assert s["min_is_bound"] is False and s["max_c"] is None


def test_real_clean_frames_have_no_over_block() -> None:
    res = _track_real(250.0)
    for k in (0, 1, 5):
        assert res[k].over_range is False and res[k].over_stats is None
    assert res[2].over_stats is not None and res[2].over_stats["sample"]["over_px"] == 1


def test_all_sample_pixels_over_range_bounds_min_too() -> None:
    t = SmartTracker(_spec(), W, H)
    first = t.update(_blob(), 0.0)
    assert first.bbox is not None and first.labels is not None
    core = np.zeros((H, W), dtype=bool)  # every pixel of the locked outline (and a margin) wraps
    x0, y0, x1, y1 = first.bbox
    core[y0:y1, x0:x1] = first.labels == 1
    core = np.asarray(core | (_rho(rx=RX + 3, ry=RY + 3) <= 1.0), dtype=bool)
    frame = _blob()
    frame[core] = -60.0  # wrapped
    r = t.update(frame, 1 / 30, over=core, ceiling_c=250.0)
    assert r.over_range is True and r.over_stats is not None
    s = r.over_stats["sample"]
    assert s["over_px"] == int((r.labels == 1).sum())
    assert s["mean_lb_c"] == 250.0 and s["min_c"] == 250.0 and s["min_is_bound"] is True


def test_unknown_ceiling_counts_over_pixels_at_the_in_range_max() -> None:
    """No camera case known: the true value still exceeds every in-range pixel, so the in-range max
    is a valid (weaker) floor; the ceiling is reported unknown."""
    frame = _blob()
    core = _rho(rx=RX / 3, ry=RY / 3) <= 1.0
    frame[core] = -60.0
    t = SmartTracker(_spec(), W, H)
    r = t.update(frame, 0.0, over=core)
    s = r.over_stats["sample"]
    x0, y0, x1, y1 = r.bbox
    m = r.labels == 1
    vals, sat = frame[y0:y1, x0:x1][m], core[y0:y1, x0:x1][m]
    good = vals[~sat]
    assert s["ceiling_c"] is None
    assert abs(s["mean_lb_c"] - (good.sum() + sat.sum() * good.max()) / vals.size) < 1e-9
    assert s["min_c"] == float(good.min())


def test_ring_over_range_alone_keeps_the_sample_valid() -> None:
    """Over-range only in a ring band: the sample stays a valid reading; the ring gets bounds."""
    frame = _blob()
    t = SmartTracker(_spec(), W, H)
    first = t.update(frame, 0.0)
    rho = _rho()
    ring_px = (rho > 1.0) & (rho < 1.08) & (np.mgrid[0:H, 0:W][1] > CX + RX)  # right edge, ring 0
    frame2 = frame.copy()
    frame2[ring_px] = -60.0
    r = t.update(frame2, 1 / 30, over=ring_px, ceiling_c=250.0)
    assert r.valid is True and r.over_range is False
    assert r.sample["mean_c"] is not None and first.sample["mean_c"] is not None
    assert abs(r.sample["mean_c"] - first.sample["mean_c"]) < 1.0  # a plain, valid reading
    assert r.rings[0]["mean_c"] is None  # unchanged: an over-range ring has no plain numbers
    assert r.over_stats is not None
    assert r.over_stats["sample"]["over_px"] == 0
    assert r.over_stats["sample"]["max_c"] == r.sample["max_c"]
    g = r.over_stats["rings"][0]
    assert g["over_px"] > 0 and g["ceiling_c"] == 250.0 and g["max_c"] is None
    assert g["min_c"] is not None and g["min_c"] > 0
    outer = r.over_stats["rings"][2]
    assert outer["over_px"] == 0 and outer["mean_lb_c"] == r.rings[2]["mean_c"]


def test_emissivity_recorrects_the_ceiling_like_any_pixel() -> None:
    rbf = Radiometry(22474.88, 1520.0, 1.05)
    cam = {
        "calibration_constants": {"R": rbf.R, "B": rbf.B, "F": rbf.F},
        "object_parameters": {"ObjectEmissivity": 0.95, "ReflectedTemperature": 293.15},
    }
    frame = _blob()
    core = _rho(rx=RX / 3, ry=RY / 3) <= 1.0
    frame[core] = -60.0
    t = SmartTracker(_spec(), W, H, cam=cam, optics={"emissivity": 0.8})
    r = t.update(frame, 0.0, over=core, ceiling_c=250.0)
    want = float(recorrect_celsius(np.array([250.0]), rbf, eps_cam=0.95, trefl_cam_k=293.15,
                                   eps=0.8, trefl_k=293.15)[0])
    assert abs(r.over_stats["sample"]["ceiling_c"] - want) < 1e-6


# --- wire + feed contract -------------------------------------------------------------------------


def test_overlay_carries_the_over_block_only_when_over_range() -> None:
    res = _track_real(250.0)
    clean = smart_overlay(res[0], 113)
    assert "over" not in clean  # unchanged shape for a healthy frame
    o = smart_overlay(res[3], 113)
    assert o["valid"] is False and o["state"] == "locked"
    assert o["over"]["sample"] == res[3].over_stats["sample"]
    assert len(o["over"]["rings"]) == 3
    assert all(set(g) == STAT_KEYS for g in o["over"]["rings"])


def test_feed_contract_unchanged_for_over_range() -> None:
    """TC-POWER safety contract: the over-range ROI stays invalid with null temperatures and the
    entry carries exactly the keys it always had (no bounded numbers leak into the feed)."""
    celsius, over, spec, high = _real()
    fx = np.load(FIXTURE)
    counts = fx["counts"][3]
    res = _track_real(high)[3]
    res.frame_ts_ns = 1_000
    roi = {"id": 113, "kind": "smart", "name": "cube",
           "search": [list(p) for p in spec.search], "rings_px": list(spec.rings_px)}
    p = live_roi_payload(counts=counts, ir_format=str(fx["ir_format"]), rois=[roi],
                         acquiring=True, frame_id=1, host_ts_ns=1_000, now_ns=2_000,
                         smart={113: res})
    e = p["rois"][0]
    assert set(e) == {"id", "name", "kind", "mean_c", "max_c", "min_c", "value_c", "over_range",
                      "valid", "state", "rings", "dims"}
    assert e["valid"] is False and e["over_range"] is True and e["state"] == "locked"
    assert e["mean_c"] is None and e["max_c"] is None and e["min_c"] is None
    assert all(g["mean_c"] is None and g["max_c"] is None and g["min_c"] is None
               for g in e["rings"])
    assert e["dims"] is None
