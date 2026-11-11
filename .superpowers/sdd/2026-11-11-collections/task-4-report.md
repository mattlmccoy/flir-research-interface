# Task 4 report: operator busy predicate

Implemented `backend/flir_research_interface/busy.py` (BusyInputs, busy_reasons), `_busy()` and `GET /api/operator/busy` in api/app.py.
Real names used: `app.state.finalizing` (set), `app.state.armer`, `control_last`, `rf_link_last_event`, `rf_engaged(control_last, rf_last, now)`, `render_tasks`, job dicts.
Smart job keys are (run key, roi id) tuples; label is "smart <run key> <roi id>".

TDD: RED = `pytest tests/test_busy.py` -> ModuleNotFoundError flir_research_interface.busy. GREEN = 9 passed.
Tests: idle, parametrized per-signal, fixed order, API post-stop test (slow run_summary held; busy shows "1 background task(s)" after stop, then clears).
Full suite: exit 1, only failure tests/test_smart_roi.py::test_update_is_fast (14.35 ms/frame, known timing flake). ruff clean (after fixing a long line in test), mypy clean.
Files: backend/flir_research_interface/busy.py, backend/tests/test_busy.py, backend/flir_research_interface/api/app.py

## Fix round 1

Bug: `" ".join(key)` on smart_jobs keys `(run_key, roi_id:int)` raised TypeError, so /api/operator/busy returned 500 while a smart job ran.
Fix: pure `job_labels(jobs)` in busy.py (stringifies tuple keys); `_busy()` uses it; comment on intentional double-reporting.

RED: `pytest tests/test_busy.py -k smart_job_is_reported` -> `assert 500 == 200` (server TypeError: `" ".join(("mattmccoy/r", 3))` -> "sequence item 1: expected str instance, int found"); unit test -> ImportError (job_labels missing).
GREEN: `pytest tests/test_busy.py` -> 11 passed. ruff clean, mypy clean.
Full suite (`pytest -q -p no:warnings > file`): only failure test_smart_roi.py::test_update_is_fast (7.18 ms/frame, known flake).
