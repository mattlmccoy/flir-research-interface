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


def test_title_and_notes_round_trip_and_are_normalized(tmp_path: Path) -> None:
    stored = write_labels(tmp_path, starred=False, tags=[], title="  doped   coupon  #3 ",
                          notes="  line one\nline two  \n")
    assert stored["title"] == "doped coupon #3"  # whitespace collapsed, trimmed
    assert stored["notes"] == "line one\nline two"  # line breaks kept, ends trimmed
    assert read_labels(tmp_path)["title"] == "doped coupon #3"
    long = write_labels(tmp_path, starred=False, tags=[], title="x" * 500, notes="n" * 20000)
    assert len(long["title"]) == 120 and len(long["notes"]) == 10000  # capped


def test_star_or_tag_edit_keeps_title_and_notes(tmp_path: Path) -> None:
    write_labels(tmp_path, starred=False, tags=["a"], title="Run A", notes="kept")
    write_labels(tmp_path, starred=True, tags=["a", "b"])  # e.g. a bulk star from an older client
    got = read_labels(tmp_path)
    assert got == {"starred": True, "tags": ["a", "b"], "title": "Run A", "notes": "kept"}


def test_blank_title_or_notes_clears_them(tmp_path: Path) -> None:
    write_labels(tmp_path, starred=False, tags=[], title="Run A", notes="n")
    write_labels(tmp_path, starred=False, tags=[], title="  ", notes="")
    assert read_labels(tmp_path) == {"starred": False, "tags": []}  # keys absent when unset


def test_export_label_uses_display_name_with_the_timestamp_kept(tmp_path: Path) -> None:
    from flir_research_interface.labels import export_label

    run = tmp_path / "20260911_121421_Run"
    run.mkdir()
    assert export_label(run) == "20260911_121421_Run"  # no display name: folder name, unchanged
    write_labels(run, starred=False, tags=[], title="Doped coupon #3")
    assert export_label(run) == "20260911_121421_Doped_coupon_3"
    write_labels(run, starred=False, tags=[], title='Ø? bad:/\\*"<>| chars  é')
    label = export_label(run)  # filesystem- and header-safe on Windows/macOS/Linux
    assert label.startswith("20260911_121421_") and label.isascii()
    assert not any(c in label for c in '<>:"/\\|?* ')
    write_labels(run, starred=False, tags=[], title="x" * 300)
    assert len(export_label(run)) <= 100
    other = tmp_path / "run1"  # a folder without the timestamp prefix keeps its name as the prefix
    other.mkdir()
    write_labels(other, starred=False, tags=[], title="Coupon")
    assert export_label(other) == "run1_Coupon"
