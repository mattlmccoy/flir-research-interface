"""Profile builder: an offline library of applications/materials → suggested metadata fields
and mark buttons, matched by keywords in a free-text description."""

from __future__ import annotations

from fastapi.testclient import TestClient

from flir_research_interface.analysis.profile_library import LIBRARY, suggest
from flir_research_interface.api.app import create_app


def test_library_entries_are_well_formed_and_keys_unique_within_an_entry() -> None:
    assert len(LIBRARY) >= 25
    for e in LIBRARY:
        assert e["id"] and e["title"] and e["keywords"] and e["fields"]
        keys = [f["key"] for f in e["fields"]]
        assert len(keys) == len(set(keys))
        for f in e["fields"]:
            assert f["type"] in ("text", "number") and f["label"] and f["why"]


def test_suggest_matches_materials_and_processes_and_merges_fields() -> None:
    s = suggest("heating nylon PA12 powder with RF at 13.56 MHz")
    ids = [m["id"] for m in s["matches"]]
    assert "polymer" in ids and "powder" in ids and "rf_dielectric" in ids
    keys = [f["key"] for f in s["fields"]]
    assert "rf_frequency_mhz" in keys and "particle_size_d50_um" in keys and "polymer_grade" in keys
    assert len(keys) == len(set(keys)), "merged without duplicates"
    assert any(m["label"] == "RF ON" for m in s["marks"])
    assert s["fields"][0]["source"]  # every suggestion says which entry proposed it


def test_suggest_handles_synonyms_case_and_nothing() -> None:
    s = suggest("Aluminium plate heated by INDUCTION coil")
    ids = [m["id"] for m in s["matches"]]
    assert "metal" in ids and "induction" in ids
    assert "polymer" not in [m["id"] for m in s["matches"]], "'plate' must not match 'pla'"
    empty = suggest("")
    assert empty["matches"] == [] and [f["key"] for f in empty["fields"]][:2] == [
        "operator",
        "sample_id",
    ]
    assert suggest("zzz nothing here")["matches"] == []


def test_suggest_route() -> None:
    with TestClient(create_app()) as c:
        r = c.get("/api/profile/suggest", params={"q": "silicone resin curing"})
        assert r.status_code == 200
        ids = [m["id"] for m in r.json()["matches"]]
        assert "resin" in ids and "curing" in ids


def test_library_covers_common_a70_research_uses() -> None:
    cases = {
        "heat exchanger fin tube effectiveness": "heat_exchanger",
        "pulsed thermography lock-in NDT of a CFRP panel": "active_ndt",
        "semiconductor die hotspot on a wafer": "semiconductor",
        "sample inside a vacuum chamber with a germanium window": "chamber",
        "injection moulding cavity cooling": "moulding",
        "natural convection heat transfer coefficient on a heated plate": "convection",
        "engine exhaust manifold and turbocharger": "automotive",
        "server rack thermal management airflow": "datacenter",
        "cold storage insulation pallets": "cold_chain",
        "concrete curing bridge deck delamination": "civil",
    }
    for text, expected in cases.items():
        ids = [m["id"] for m in suggest(text)["matches"]]
        assert expected in ids, f"{text!r} → {ids}"
