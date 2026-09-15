"""Per-run organization sidecar: normalize tags, read/write labels.json (tolerant + atomic)."""

from __future__ import annotations

from pathlib import Path

from flir_research_interface.labels import normalize_tags, read_labels, write_labels


def test_normalize_tags_trims_dedupes_caseins_preserves_first_casing_and_order() -> None:
    out = normalize_tags(["  Doped ", "doped", "8020mix", "", "   ", "a" * 60, "  two words  "])
    assert out == ["Doped", "8020mix", "a" * 40, "two words"]  # trimmed, deduped, capped, ordered


def test_read_labels_defaults_when_missing_or_corrupt(tmp_path: Path) -> None:
    assert read_labels(tmp_path) == {"starred": False, "tags": []}
    (tmp_path / "labels.json").write_text("{not json")
    assert read_labels(tmp_path) == {"starred": False, "tags": []}


def test_write_labels_normalizes_and_round_trips_atomically(tmp_path: Path) -> None:
    stored = write_labels(tmp_path, starred=True, tags=["Doped", "doped", " x "])
    assert stored == {"starred": True, "tags": ["Doped", "x"]}
    assert read_labels(tmp_path) == {"starred": True, "tags": ["Doped", "x"]}
    assert not list(tmp_path.glob("*.tmp*"))  # temp file cleaned up (atomic replace)
