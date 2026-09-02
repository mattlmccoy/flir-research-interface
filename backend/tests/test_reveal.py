"""Reveal-in-file-manager: command selection, path containment, endpoint."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.api.reveal import _default_runner, contained, reveal, reveal_command


def test_reveal_command_per_os(tmp_path: Path) -> None:
    p = tmp_path / "exp"
    assert reveal_command("Darwin", p) == ["open", "-R", str(p)]
    assert reveal_command("Windows", p) == ["explorer", "/select,", str(p)]
    assert reveal_command("Linux", p) == ["xdg-open", str(p)]
    with pytest.raises(ValueError):
        reveal_command("Plan9", p)


def test_contained_accepts_symlinked_root_and_rejects_escapes(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "a").mkdir()
    link = tmp_path / "experiments"
    link.symlink_to(real)
    outside = tmp_path / "outside"
    outside.mkdir()
    (real / "link").symlink_to(outside)

    assert contained(link, link) is True
    assert contained(link, link / "a") is True
    assert contained(link, link / ".." / "outside") is False
    assert contained(link, link / "link") is False
    assert contained(link, link / "missing") is False


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


def test_reveal_windows_nonzero_exit_still_reports_ok(tmp_path: Path) -> None:
    # Explorer is known to return a non-zero exit code even when it successfully opens.
    res = reveal(tmp_path, system="Windows", runner=lambda _c: 1)
    assert res["ok"] is True


def test_reveal_default_runner_omitted_uses_module_default(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def spy(cmd: list[str]) -> int:
        calls.append(cmd)
        return 0

    # runner not passed at all -- exercises the `runner: Runner | None = None` default path.
    res = reveal(tmp_path, system="Darwin", runner=spy)
    assert res["ok"] is True and calls


@pytest.mark.skipif(os.name != "posix", reason="characterizes the POSIX default runner")
@pytest.mark.parametrize(
    ("cmd", "expected_rc"),
    [
        (["true"], 0),
        (["false"], 1),
        (["definitely-not-a-real-binary"], 127),
    ],
)
def test_default_runner_characterization(cmd: list[str], expected_rc: int) -> None:
    assert _default_runner(cmd) == expected_rc


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


def test_reveal_root_reports_500_when_root_cannot_be_created(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    bad_root = blocker / "experiments"  # parent exists as a file, so mkdir() must raise
    app = create_app(experiments_root=bad_root, reveal_runner=lambda _c: 0)
    with TestClient(app) as c:
        r = c.post("/api/experiments/reveal-root")
        assert r.status_code == 500


def test_exp_dir_rejects_symlinked_experiment_escaping_root(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "metadata.json").write_text("{}")
    (outside / "preview.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (root / "escape").symlink_to(outside)
    with TestClient(create_app(experiments_root=root)) as c:
        assert c.get("/api/experiments/escape/preview.png").status_code == 400
        assert c.post("/api/experiments/escape/reveal").status_code == 400
