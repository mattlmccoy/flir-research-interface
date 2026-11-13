"""Auto-offload: each finished run is queued and moved to the SSD when it is safe to.

The queue file is hand-made in the shape ``offload.py`` writes; the move itself is the real
``storage.move_experiment`` (hash while copying, re-read, then delete the Mac copy).
"""
from __future__ import annotations

import json
from pathlib import Path

from flir_research_interface.offload import (
    MAX_ATTEMPTS,
    RETRY_S,
    decide,
    finish,
    load_offload,
    queue_run,
    record_failure,
    retry_all,
    set_enabled,
)


def _entry(**over: object) -> dict:
    e = {"collection": "rf-heating", "name": "20261112_150000_run", "queued": 0.0,
         "attempts": 0, "last_try": None, "error": None}
    e.update(over)
    return e


IDLE = dict(drive=True, idle=True, src_exists=True, dst_exists=False, run_busy=False)


def test_on_by_default_and_queue_is_deduplicated(tmp_path: Path) -> None:
    assert load_offload(tmp_path) == {"enabled": True, "pending": []}
    queue_run(tmp_path, "rf-heating", "r1", now=1.0)
    queue_run(tmp_path, "rf-heating", "r1", now=2.0)
    assert [e["name"] for e in load_offload(tmp_path)["pending"]] == ["r1"]
    set_enabled(tmp_path, False)
    assert load_offload(tmp_path)["enabled"] is False
    assert len(load_offload(tmp_path)["pending"]) == 1  # turning off keeps the queue


def test_finish_and_failures(tmp_path: Path) -> None:
    queue_run(tmp_path, "c", "r1", now=1.0)
    record_failure(tmp_path, "c", "r1", "SSD went away", now=5.0)
    (e,) = load_offload(tmp_path)["pending"]
    assert (e["attempts"], e["last_try"], e["error"]) == (1, 5.0, "SSD went away")
    retry_all(tmp_path)
    (e,) = load_offload(tmp_path)["pending"]
    assert (e["attempts"], e["error"]) == (0, None)
    finish(tmp_path, "c", "r1")
    assert load_offload(tmp_path)["pending"] == []


def test_a_corrupt_queue_file_is_not_clobbered(tmp_path: Path) -> None:
    (tmp_path / ".auto-offload.json").write_text("{broken")
    assert load_offload(tmp_path)["pending"] == []
    queue_run(tmp_path, "c", "r1", now=1.0)
    assert (tmp_path / ".auto-offload.json").read_text() == "{broken"


def test_decide_moves_only_when_everything_is_ready() -> None:
    assert decide(_entry(), now=100.0, **IDLE) == "move"
    assert decide(_entry(), now=100.0, **{**IDLE, "drive": False}) == "wait:SSD not connected"
    assert decide(_entry(), now=100.0, **{**IDLE, "idle": False}) == "wait:a recording is active"
    assert decide(_entry(), now=100.0, **{**IDLE, "run_busy": True}) == "wait:finishing exports"


def test_decide_recognises_done_gone_and_clash() -> None:
    assert decide(_entry(), now=1.0, **{**IDLE, "src_exists": False, "dst_exists": True}) == "done"
    assert decide(_entry(), now=1.0, **{**IDLE, "src_exists": False}) == "gone"
    assert decide(_entry(), now=1.0, **{**IDLE, "dst_exists": True}) == "clash"


def test_decide_backs_off_then_gives_up() -> None:
    e = _entry(attempts=2, last_try=1000.0)
    assert decide(e, now=1000.0 + 2 * RETRY_S - 1, **IDLE) == "wait:retrying soon"
    assert decide(e, now=1000.0 + 2 * RETRY_S, **IDLE) == "move"
    assert decide(_entry(attempts=MAX_ATTEMPTS, last_try=0.0), now=1e9, **IDLE) == "stuck"


def test_queue_survives_as_json(tmp_path: Path) -> None:
    queue_run(tmp_path, "c", "r1", now=1.0)
    doc = json.loads((tmp_path / ".auto-offload.json").read_text())
    assert doc["pending"][0]["collection"] == "c"
