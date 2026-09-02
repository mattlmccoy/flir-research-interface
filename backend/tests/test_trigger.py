"""M11: armed recording. A pure state machine decides when a recording starts and stops from a
stream of (t_s, frame_index, watched value) samples; the operator wires it to the camera."""

from __future__ import annotations

import pytest

from flir_research_interface.recording.trigger import (
    EndCondition,
    StartCondition,
    TriggerMachine,
    TriggerSpec,
    parse_trigger,
)


def _run(m: TriggerMachine, samples: list[tuple[float, float | None]]) -> list[tuple[int, str]]:
    out = []
    for i, (t, v) in enumerate(samples):
        a = m.feed(t, i, v)
        if a:
            out.append((i, a))
    return out


def test_threshold_start_needs_the_level_sustained_and_frames_end() -> None:
    spec = TriggerSpec(
        start=StartCondition(kind="threshold", level_c=50.0, direction="rising", sustain_frames=3),
        end=EndCondition(kind="frames", frames=4),
    )
    m = TriggerMachine(spec)
    assert m.state == "armed"
    samples = [
        (0.0, 20.0),
        (0.1, 55.0),
        (0.2, 55.0),
        (0.3, 40.0),  # spike, not sustained
        (0.4, 60.0),
        (0.5, 60.0),
        (0.6, 60.0),  # 3 in a row -> start at index 6
        (0.7, 61.0),
        (0.8, 61.0),
        (0.9, 61.0),
        (1.0, 61.0),
    ]  # 4 frames recorded -> stop at 9
    assert _run(m, samples) == [(6, "start"), (9, "stop")]
    assert m.state == "done" and m.started_at_index == 6 and m.reason == "frames"


def test_falling_threshold_end_and_duration_end() -> None:
    spec = TriggerSpec(
        start=StartCondition(kind="manual"),
        end=EndCondition(kind="threshold", level_c=30.0, direction="falling", sustain_frames=2),
    )
    m = TriggerMachine(spec)
    assert m.feed(0.0, 0, 80.0) is None  # manual start: nothing happens until start() is called
    m.start(0.0, 0)
    assert m.state == "recording"
    assert _run(m, [(0.1, 80.0), (0.2, 25.0), (0.3, 25.0)]) == [(2, "stop")]
    assert m.reason == "threshold"

    spec2 = TriggerSpec(
        start=StartCondition(kind="after", after_s=1.0),
        end=EndCondition(kind="duration", seconds=2.0),
    )
    m2 = TriggerMachine(spec2)
    assert _run(
        m2, [(0.0, None), (0.5, None), (1.0, None), (2.0, None), (3.0, None), (3.1, None)]
    ) == [(2, "start"), (4, "stop")]


def test_none_values_never_trigger_and_the_safety_cap_always_ends() -> None:
    spec = TriggerSpec(
        start=StartCondition(kind="threshold", level_c=50.0, direction="rising", sustain_frames=1),
        end=EndCondition(kind="manual"),
        max_seconds=5.0,
    )
    m = TriggerMachine(spec)
    assert _run(m, [(0.0, None), (0.1, None)]) == []
    assert _run(m, [(1.0, 70.0), (3.0, 70.0), (6.5, 70.0)]) == [(0, "start"), (2, "stop")]
    assert m.reason == "max_seconds"


def test_parse_trigger_validates_and_fills_defaults() -> None:
    spec = parse_trigger(
        {
            "start": {
                "kind": "threshold",
                "roi": 2,
                "stat": "max",
                "level_c": 80,
                "direction": "rising",
            },
            "end": {"kind": "duration", "seconds": 90},
            "pretrigger_s": 2,
        }
    )
    assert spec.start.roi == 2 and spec.start.stat == "max" and spec.start.sustain_frames == 3
    assert spec.end.seconds == 90 and spec.pretrigger_s == 2.0 and spec.max_seconds == 1800.0
    with pytest.raises(ValueError):
        parse_trigger({"start": {"kind": "threshold"}, "end": {"kind": "manual"}})  # no level
    with pytest.raises(ValueError):
        parse_trigger({"start": {"kind": "manual"}, "end": {"kind": "frames", "frames": 0}})
    with pytest.raises(ValueError):
        parse_trigger({"start": {"kind": "sideways"}, "end": {"kind": "manual"}})
