"""Whether the RF generator (T&C/CXN tool) is currently linked to FLIR.

FLIR only learns the link exists when the RF tool posts to it — an RF on/off edge
(/api/rf-link/event) or a control-telemetry tick (/api/control/telemetry). The link is considered
*engaged* while those posts are recent; when they stop (loop stopped, generator disconnected, tool
closed) it lapses, so the RF/closed-loop UI can hide itself instead of showing stale state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# Control telemetry ticks at ~2 Hz; an RF edge only fires on a transition. Give the edge a much
# longer grace so "RF on, holding" (no new posts) still counts as linked.
CONTROL_FRESH_S = 10.0
RF_EVENT_FRESH_S = 120.0


def _age_s(ts_iso: str | None, now: datetime) -> float | None:
    if not ts_iso:
        return None
    try:
        return (now - datetime.fromisoformat(ts_iso)).total_seconds()
    except ValueError:
        return None


def rf_engaged(
    control_last: dict[str, Any] | None,
    rf_last: dict[str, Any] | None,
    now: datetime,
    *,
    control_fresh_s: float = CONTROL_FRESH_S,
    rf_event_fresh_s: float = RF_EVENT_FRESH_S,
) -> bool:
    """True when FLIR has heard from the RF tool recently (fresh control tick or RF edge)."""
    c_age = _age_s((control_last or {}).get("ts"), now)
    if c_age is not None and 0 <= c_age <= control_fresh_s:
        return True
    r_age = _age_s((rf_last or {}).get("ts"), now)
    return r_age is not None and 0 <= r_age <= rf_event_fresh_s


__all__ = ["rf_engaged", "CONTROL_FRESH_S", "RF_EVENT_FRESH_S"]
