"""RF-link engagement: is the RF generator currently linked to FLIR (recent posts)?"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flir_research_interface.rf_status import rf_engaged


def _iso(now: datetime, ago_s: float) -> str:
    return (now - timedelta(seconds=ago_s)).isoformat()


def test_not_engaged_when_nothing_received() -> None:
    now = datetime.now(timezone.utc)
    assert rf_engaged(None, None, now) is False


def test_engaged_on_a_fresh_control_tick() -> None:
    now = datetime.now(timezone.utc)
    assert rf_engaged({"ts": _iso(now, 1.0)}, None, now) is True
    # a stale control tick alone does not count
    assert rf_engaged({"ts": _iso(now, 30.0)}, None, now) is False


def test_engaged_on_a_recent_rf_edge_even_without_telemetry() -> None:
    now = datetime.now(timezone.utc)
    # RF held on: last edge 90 s ago, no telemetry — still linked (edges are sparse)
    assert rf_engaged(None, {"ts": _iso(now, 90.0)}, now) is True
    # but a very old edge lapses
    assert rf_engaged(None, {"ts": _iso(now, 600.0)}, now) is False


def test_malformed_or_missing_ts_is_not_engaged() -> None:
    now = datetime.now(timezone.utc)
    assert rf_engaged({"ts": "not-a-date"}, {"ts": None}, now) is False
    assert rf_engaged({}, {}, now) is False
