"""M10: one-command operator install (macOS launchd first): .env writing, LaunchAgent plist,
and a doctor report that never shows unknown as healthy."""

from __future__ import annotations

import plistlib
from pathlib import Path

from flir_research_interface.install import (
    LABEL,
    doctor,
    launchd_plist,
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
