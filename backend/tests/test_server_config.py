"""Operator config resolution: where the experiments directory comes from.

The experiments live outside the checkout (e.g. a Dropbox folder), so the location must be
configurable and survive updates. It is read from FRI_EXPERIMENTS_ROOT — the process environment
(set by the service) or the git-ignored backend/.env (which `git pull` never touches).
"""

from __future__ import annotations

from flir_research_interface.api.server import resolve_experiments_root


def test_env_wins_then_dotenv_then_none() -> None:
    assert resolve_experiments_root({"FRI_EXPERIMENTS_ROOT": "/a"},
                                    {"FRI_EXPERIMENTS_ROOT": "/b"}) == "/a"
    assert resolve_experiments_root({}, {"FRI_EXPERIMENTS_ROOT": "/b"}) == "/b"
    assert resolve_experiments_root({}, {}) is None  # unset → caller keeps its default


def test_blank_or_whitespace_is_treated_as_unset() -> None:
    assert resolve_experiments_root({"FRI_EXPERIMENTS_ROOT": "   "}, {}) is None
    assert resolve_experiments_root({"FRI_EXPERIMENTS_ROOT": ""},
                                    {"FRI_EXPERIMENTS_ROOT": "/b"}) == "/b"  # blank env falls back
    # surrounding whitespace is trimmed
    assert resolve_experiments_root({"FRI_EXPERIMENTS_ROOT": "  /a/b  "}, {}) == "/a/b"
