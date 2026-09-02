"""M11: armed recording — a pure trigger state machine.

The operator arms a recording with a *start* condition (manual, after N seconds, or a watched ROI
statistic crossing a level, sustained for a few frames to reject noise) and an *end* condition
(manual, N frames, N seconds, or a threshold), plus a hard ``max_seconds`` cap that always applies.
``TriggerMachine.feed`` is called once per frame with the sample time, frame index and the watched
value (``None`` when the ROI cannot be evaluated) and returns ``"start"``, ``"stop"`` or ``None``.
Nothing here touches the camera or the store; the API wires it to the acquisition thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

StartKind = Literal["manual", "after", "threshold"]
EndKind = Literal["manual", "frames", "duration", "threshold"]
Direction = Literal["rising", "falling"]
Stat = Literal["value", "mean", "min", "max"]

DEFAULT_SUSTAIN = 3
DEFAULT_MAX_SECONDS = 1800.0
DEFAULT_PRETRIGGER_S = 2.0


@dataclass(frozen=True)
class StartCondition:
    kind: StartKind
    after_s: float | None = None
    roi: int | None = None
    stat: Stat = "mean"
    level_c: float | None = None
    direction: Direction = "rising"
    sustain_frames: int = DEFAULT_SUSTAIN


@dataclass(frozen=True)
class EndCondition:
    kind: EndKind
    frames: int | None = None
    seconds: float | None = None
    roi: int | None = None
    stat: Stat = "mean"
    level_c: float | None = None
    direction: Direction = "falling"
    sustain_frames: int = DEFAULT_SUSTAIN


@dataclass(frozen=True)
class TriggerSpec:
    start: StartCondition
    end: EndCondition
    pretrigger_s: float = DEFAULT_PRETRIGGER_S
    max_seconds: float = DEFAULT_MAX_SECONDS

    def as_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


def _crossed(value: float, level: float, direction: Direction) -> bool:
    return value >= level if direction == "rising" else value <= level


class TriggerMachine:
    """States: armed → recording → done. Not thread-safe; feed from one thread."""

    def __init__(self, spec: TriggerSpec) -> None:
        self.spec = spec
        self.state: Literal["armed", "recording", "done"] = "armed"
        self.armed_t: float | None = None
        self.started_t: float | None = None
        self.started_at_index: int | None = None
        self.frames_recorded = 0
        self.reason: str | None = None
        self._sustain = 0

    # -- transitions ---------------------------------------------------------------------------

    def start(self, t_s: float, index: int) -> None:
        self.state = "recording"
        self.started_t = t_s
        self.started_at_index = index
        self.frames_recorded = 0
        self._sustain = 0

    def stop(self, reason: str) -> None:
        self.state = "done"
        self.reason = reason

    # -- per-frame -----------------------------------------------------------------------------

    def feed(self, t_s: float, index: int, value: float | None) -> str | None:
        if self.armed_t is None:
            self.armed_t = t_s
        if self.state == "armed":
            if self._start_due(t_s, value):
                self.start(t_s, index)
                self.frames_recorded = 1
                return "start"
            return None
        if self.state == "recording":
            self.frames_recorded += 1
            reason = self._end_due(t_s, value)
            if reason:
                self.stop(reason)
                return "stop"
        return None

    def _start_due(self, t_s: float, value: float | None) -> bool:
        s = self.spec.start
        if s.kind == "manual":
            return False
        if s.kind == "after":
            return self.armed_t is not None and t_s - self.armed_t >= float(s.after_s or 0.0)
        return self._sustained(value, s.level_c, s.direction, s.sustain_frames)

    def _end_due(self, t_s: float, value: float | None) -> str | None:
        e = self.spec.end
        elapsed = t_s - (self.started_t or t_s)
        if elapsed >= self.spec.max_seconds:
            return "max_seconds"
        if e.kind == "frames" and e.frames is not None and self.frames_recorded >= e.frames:
            return "frames"
        if e.kind == "duration" and e.seconds is not None and elapsed >= e.seconds:
            return "duration"
        if e.kind == "threshold" and self._sustained(
            value, e.level_c, e.direction, e.sustain_frames
        ):
            return "threshold"
        return None

    def _sustained(
        self, value: float | None, level: float | None, direction: Direction, n: int
    ) -> bool:
        if value is None or level is None or value != value:  # None / NaN never count
            self._sustain = 0
            return False
        self._sustain = self._sustain + 1 if _crossed(value, level, direction) else 0
        return self._sustain >= max(1, n)

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "started_at_index": self.started_at_index,
            "frames_recorded": self.frames_recorded,
            "reason": self.reason,
            "sustain": self._sustain,
        }


# -- parsing -------------------------------------------------------------------------------------


def _num(v: Any, name: str, *, lo: float | None = None) -> float:
    if isinstance(v, bool) or not isinstance(v, int | float):
        raise ValueError(f"{name} must be a number")
    if lo is not None and v < lo:
        raise ValueError(f"{name} must be >= {lo}")
    return float(v)


def _threshold_fields(d: dict[str, Any], default_dir: Direction) -> dict[str, Any]:
    if d.get("level_c") is None:
        raise ValueError("threshold needs level_c")
    stat = d.get("stat", "mean")
    if stat not in ("value", "mean", "min", "max"):
        raise ValueError("stat must be value, mean, min or max")
    direction = d.get("direction", default_dir)
    if direction not in ("rising", "falling"):
        raise ValueError("direction must be rising or falling")
    roi = d.get("roi")
    if roi is not None and (isinstance(roi, bool) or not isinstance(roi, int)):
        raise ValueError("roi must be an ROI id")
    sustain = d.get("sustain_frames", DEFAULT_SUSTAIN)
    return {
        "roi": roi,
        "stat": stat,
        "level_c": _num(d["level_c"], "level_c"),
        "direction": direction,
        "sustain_frames": int(_num(sustain, "sustain_frames", lo=1)),
    }


def parse_trigger(raw: dict[str, Any]) -> TriggerSpec:
    if not isinstance(raw, dict):
        raise ValueError("trigger must be an object")
    s, e = raw.get("start") or {}, raw.get("end") or {}
    sk, ek = s.get("kind", "manual"), e.get("kind", "manual")
    if sk == "manual":
        start = StartCondition(kind="manual")
    elif sk == "after":
        start = StartCondition(kind="after", after_s=_num(s.get("after_s", 0), "after_s", lo=0))
    elif sk == "threshold":
        start = StartCondition(kind="threshold", **_threshold_fields(s, "rising"))
    else:
        raise ValueError(f"unknown start kind {sk!r}")
    if ek == "manual":
        end = EndCondition(kind="manual")
    elif ek == "frames":
        end = EndCondition(kind="frames", frames=int(_num(e.get("frames"), "frames", lo=1)))
    elif ek == "duration":
        end = EndCondition(kind="duration", seconds=_num(e.get("seconds"), "seconds", lo=0.1))
    elif ek == "threshold":
        end = EndCondition(kind="threshold", **_threshold_fields(e, "falling"))
    else:
        raise ValueError(f"unknown end kind {ek!r}")
    return TriggerSpec(
        start=start,
        end=end,
        pretrigger_s=_num(raw.get("pretrigger_s", DEFAULT_PRETRIGGER_S), "pretrigger_s", lo=0),
        max_seconds=_num(raw.get("max_seconds", DEFAULT_MAX_SECONDS), "max_seconds", lo=1),
    )


__all__ = ["EndCondition", "StartCondition", "TriggerMachine", "TriggerSpec", "parse_trigger"]
