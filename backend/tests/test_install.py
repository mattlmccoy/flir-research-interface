"""M10: one-command operator install (macOS launchd first): .env writing, LaunchAgent plist,
and a doctor report that never shows unknown as healthy."""

from __future__ import annotations

import plistlib
from pathlib import Path

import flir_research_interface.install as install_mod
from flir_research_interface.install import (
    LAB_CAMERA_HOST,
    LAB_RTSP_PASSWORD,
    LAB_RTSP_USER,
    LABEL,
    doctor,
    launchd_plist,
    main,
    systemd_unit,
    write_env,
)


def test_launchd_plist_runs_fri_serve_at_login_with_logs_beside_the_repo(tmp_path: Path) -> None:
    data = launchd_plist(
        uv="/opt/homebrew/bin/uv",
        backend_dir=tmp_path / "backend",
        port=8000,
        site_origin="https://example.github.io",
    )
    d = plistlib.loads(data)
    assert d["Label"] == LABEL == "io.github.mattlmccoy.flir-research-interface"
    assert d["ProgramArguments"][:4] == [
        "/opt/homebrew/bin/uv",
        "run",
        "--directory",
        str(tmp_path / "backend"),
    ]
    assert "fri-serve" in d["ProgramArguments"] and "--port" in d["ProgramArguments"]
    assert (
        d["ProgramArguments"][d["ProgramArguments"].index("--site-origin") + 1]
        == "https://example.github.io"
    )
    assert d["RunAtLoad"] is True and d["KeepAlive"] is True
    assert d["WorkingDirectory"] == str(tmp_path / "backend")
    assert d["StandardOutPath"].endswith("operator.log") and d["StandardErrorPath"].endswith(
        "operator.log"
    )
    assert d["EnvironmentVariables"]["PATH"].startswith("/opt/homebrew/bin")


def test_lab_defaults_are_the_current_camera(tmp_path: Path) -> None:
    # The lab camera moved off 192.168.7.x to .8.2 on 2026-09-11; the installer must pre-fill it.
    assert LAB_CAMERA_HOST == "192.168.8.2"
    assert LAB_RTSP_USER == "rtsp"
    assert LAB_RTSP_PASSWORD == "ktEmIrar"


def test_pressing_enter_at_prompts_writes_the_baked_lab_credentials(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A labmate can accept every default (including the password) with Enter and get a working
    .env — no need to look anything up."""
    backend = tmp_path / "backend"
    backend.mkdir()
    monkeypatch.setattr(install_mod, "__file__", str(backend / "flir_research_interface" / "x.py"))
    (backend / "flir_research_interface").mkdir()
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")  # accept IP + user defaults
    monkeypatch.setattr(install_mod.getpass, "getpass", lambda _prompt="": "")  # Enter on password
    rc = main(["--no-service"])
    assert rc == 0
    env = (backend / ".env").read_text()
    assert "FRI_CAMERA_HOST=192.168.8.2" in env
    assert "FRI_RTSP_USER=rtsp" in env
    assert "FRI_RTSP_PASSWORD=ktEmIrar" in env


def test_systemd_unit_runs_fri_serve_and_restarts(tmp_path: Path) -> None:
    unit = systemd_unit(
        uv="/home/lab/.local/bin/uv",
        backend_dir=tmp_path / "backend",
        port=8000,
        site_origin="https://example.github.io",
    )
    # An INI systemd --user service, not distro-specific: works on Fedora, Ubuntu, Arch alike.
    assert "[Service]" in unit and "[Install]" in unit
    assert f"WorkingDirectory={tmp_path / 'backend'}" in unit
    exec_line = next(ln for ln in unit.splitlines() if ln.startswith("ExecStart="))
    assert "/home/lab/.local/bin/uv" in exec_line
    assert "fri-serve" in exec_line and "--port 8000" in exec_line
    assert "--site-origin https://example.github.io" in exec_line
    assert "Restart=always" in unit
    assert "WantedBy=default.target" in unit


def test_write_env_keeps_secrets_out_of_git_and_preserves_other_keys(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("OTHER=1\nFRI_RTSP_USER=old\n")
    write_env(env, host="192.168.7.2", user="rtsp", password="s3cret")
    text = env.read_text()
    assert "OTHER=1" in text and "FRI_CAMERA_HOST=192.168.7.2" in text
    assert text.count("FRI_RTSP_USER=") == 1 and "FRI_RTSP_USER=rtsp" in text
    assert "FRI_RTSP_PASSWORD=s3cret" in text
    assert oct(env.stat().st_mode & 0o777) == "0o600"


def test_doctor_reports_each_prerequisite_with_an_explicit_ok_flag(tmp_path: Path) -> None:
    rep = doctor(backend_dir=tmp_path, dotenv=tmp_path / ".env", which=lambda name: None)
    names = [c["name"] for c in rep["checks"]]
    for needed in ("uv", "ffmpeg", "Spinnaker SDK (PySpin)", "camera credentials (.env)"):
        assert needed in names
    assert all(
        c["ok"] is False
        for c in rep["checks"]
        if c["name"] in ("uv", "ffmpeg", "camera credentials (.env)")
    )
    assert rep["ok"] is False
    for c in rep["checks"]:
        assert c["detail"], c  # every failing check says what to do
