"""Smart ROI spec parsing."""

from __future__ import annotations

import json
from typing import Any

import pytest

from flir_research_interface.analysis.series import parse_rois, roi_index
from flir_research_interface.analysis.smart_roi import SmartRoiSpec, parse_smart_roi

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
    ],
)
def test_parse_smart_rejects(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        parse_smart_roi(_raw(**bad))


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
