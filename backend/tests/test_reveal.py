"""Reveal-in-file-manager: command selection, path containment, endpoint."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.api.reveal import contained, reveal, reveal_command


def test_reveal_command_per_os(tmp_path: Path) -> None:
    p = tmp_path / "exp"
    assert reveal_command("Darwin", p) == ["open", "-R", str(p)]
    assert reveal_command("Windows", p) == ["explorer", f"/select,{p}"]
    assert reveal_command("Linux", p) == ["xdg-open", str(p.parent)]
    with pytest.raises(ValueError):
        reveal_command("Plan9", p)


def test_contained_rejects_escapes_and_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    root.mkdir()
    (root / "a").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside)
    assert contained(root, root / "a") is True
    assert contained(root, root) is True
    assert contained(root, root / ".." / "outside") is False
    assert contained(root, root / "link") is False
    assert contained(root, root / "missing") is False


def test_reveal_uses_injected_runner_and_reports(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def ok(cmd: list[str]) -> int:
        calls.append(cmd)
        return 0

    res = reveal(tmp_path, system="Darwin", runner=ok)
    assert calls == [["open", "-R", str(tmp_path)]] and res["ok"] is True
    res2 = reveal(tmp_path, system="Linux", runner=lambda _c: 127)
    assert res2["ok"] is False and "xdg-open" in res2["error"]
    res3 = reveal(tmp_path, system="Plan9", runner=ok)
    assert res3["ok"] is False and "no file manager" in res3["error"]


def test_reveal_endpoints(tmp_path: Path) -> None:
    (tmp_path / "20260901_x").mkdir()
    (tmp_path / "20260901_x" / "metadata.json").write_text("{}")
    calls: list[list[str]] = []

    def runner(cmd: list[str]) -> int:
        calls.append(cmd)
        return 0

    app = create_app(experiments_root=tmp_path, reveal_runner=runner)
    with TestClient(app) as c:
        r = c.post("/api/experiments/20260901_x/reveal")
        assert (
            r.status_code == 200
            and r.json()["ok"] is True
            and r.json()["path"].endswith("20260901_x")
        )
        # httpx normalizes ".." out of the URL before the request is sent, so this never
        # reaches _exp_dir's own validation; it lands on an unmatched path. When the SPA
        # static mount is active (frontend/dist present) that mount rejects any non-GET/HEAD
        # method on an unmatched path with 405 rather than 404 -- still "rejected", not 200.
        assert c.post("/api/experiments/../etc/reveal").status_code in (400, 404, 405)
        assert c.post("/api/experiments/missing/reveal").status_code == 404
        r = c.post("/api/experiments/reveal-root")
        assert r.status_code == 200 and r.json()["ok"] is True
        assert len(calls) == 2


def test_reveal_endpoint_reports_501_when_unsupported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("flir_research_interface.api.reveal.platform.system", lambda: "Plan9")
    app = create_app(experiments_root=tmp_path, reveal_runner=lambda _c: 0)
    with TestClient(app) as c:
        assert c.post("/api/experiments/reveal-root").status_code == 501
