"""M10: one-command operator install.

``fri-install`` turns a checkout into a background operator: writes the camera credentials to the
git-ignored ``backend/.env``, installs a launchd LaunchAgent (macOS) that runs ``fri-serve`` at
login and keeps it alive, and prints a doctor report. Everything the installer cannot do itself
(the Spinnaker SDK download behind Teledyne's login) it names precisely instead of guessing.
``fri-install --doctor`` only reports. Linux (systemd --user) and Windows are documented in
docs/installation.md; the plist/env helpers here are platform-neutral and unit-tested.
"""

from __future__ import annotations

import argparse
import getpass
import os
import platform
import plistlib
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from flir_research_interface.visible.recorder import FFMPEG_CANDIDATES
from flir_research_interface.visible.rtsp import (
    ENV_HOST,
    ENV_PASSWORD,
    ENV_USER,
    credentials,
    find_ffprobe,
)

LABEL = "io.github.mattlmccoy.flir-research-interface"
DEFAULT_SITE_ORIGIN = "https://mattlmccoy.github.io"
SDK_URL = "https://www.teledynevisionsolutions.com/products/spinnaker-sdk/"

# Baked-in defaults for *this lab's* camera, so a labmate can accept every prompt with Enter. The
# owner has deliberately chosen to keep these (including the RTSP password) in the public repo: it
# is one fixed camera on a private lab subnet, used only by the group. They still land only in the
# git-ignored backend/.env on each machine; change them here if the camera or credentials change.
# moved off 192.168.7.x on 2026-09-11 to share the bench with the Vention MachineMotion.
LAB_CAMERA_HOST = "192.168.8.2"
LAB_RTSP_USER = "rtsp"
LAB_RTSP_PASSWORD = "ktEmIrar"


def launchd_plist(
    *, uv: str, backend_dir: Path, port: int, site_origin: str, host: str = "127.0.0.1"
) -> bytes:
    """A LaunchAgent that runs the operator at login and restarts it if it dies."""
    backend_dir = Path(backend_dir)
    log = backend_dir / "operator.log"
    path = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
    return plistlib.dumps(
        {
            "Label": LABEL,
            "ProgramArguments": [
                uv,
                "run",
                "--directory",
                str(backend_dir),
                "fri-serve",
                "--host",
                host,
                "--port",
                str(port),
                "--site-origin",
                site_origin,
            ],
            "WorkingDirectory": str(backend_dir),
            "RunAtLoad": True,
            "KeepAlive": True,
            "StandardOutPath": str(log),
            "StandardErrorPath": str(log),
            "EnvironmentVariables": {"PATH": path, "PYTHONUNBUFFERED": "1"},
        }
    )


def systemd_unit(
    *, uv: str, backend_dir: Path, port: int, site_origin: str, host: str = "127.0.0.1"
) -> str:
    """A systemd ``--user`` service that runs the operator and restarts it if it dies. Distro-
    neutral (Fedora, Ubuntu, Arch, openSUSE all use systemd), so it is the Linux counterpart of
    :func:`launchd_plist`."""
    backend_dir = Path(backend_dir)
    return (
        "[Unit]\n"
        "Description=FLIR Research Interface operator\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        f"WorkingDirectory={backend_dir}\n"
        f"ExecStart={uv} run --directory {backend_dir} fri-serve "
        f"--host {host} --port {port} --site-origin {site_origin}\n"
        "Restart=always\n"
        "RestartSec=2\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def install_systemd(
    backend_dir: Path, *, port: int, site_origin: str, run: Callable[..., Any]
) -> Path:
    """Write and start a systemd ``--user`` unit; enable lingering so it runs without a login
    session. Returns the unit path."""
    uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit = unit_dir / "fri-operator.service"
    unit.write_text(
        systemd_unit(uv=uv, backend_dir=backend_dir, port=port, site_origin=site_origin)
    )
    run(["systemctl", "--user", "daemon-reload"], check=True)
    run(["systemctl", "--user", "enable", "--now", "fri-operator.service"], check=True)
    run(["loginctl", "enable-linger", getpass.getuser()], check=False, capture_output=True)
    return unit


def write_env(env_path: Path, *, host: str, user: str, password: str) -> None:
    """Upsert the three camera keys into ``.env`` (mode 600); other lines are kept verbatim."""
    env_path = Path(env_path)
    keep: list[str] = []
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            key = line.split("=", 1)[0].strip()
            if key not in (ENV_HOST, ENV_USER, ENV_PASSWORD):
                keep.append(line)
    lines = keep + [f"{ENV_HOST}={host}", f"{ENV_USER}={user}", f"{ENV_PASSWORD}={password}"]
    env_path.write_text("\n".join(lines) + "\n")
    os.chmod(env_path, 0o600)


def _pyspin() -> tuple[bool, str]:
    try:
        from flir_research_interface.sdk_install import pyspin_importable

        return pyspin_importable()
    except Exception as exc:  # noqa: BLE001 - the doctor must not crash on a broken SDK
        return False, str(exc)


def doctor(
    *,
    backend_dir: Path,
    dotenv: Path,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, Any]:
    """Prerequisite report. ``ok`` is only True when every check verified positively."""
    checks: list[dict[str, Any]] = []
    uv = which("uv")
    checks.append(
        {
            "name": "uv",
            "ok": uv is not None,
            "detail": uv
            or "install with `brew install uv` (macOS) or see https://docs.astral.sh/uv/",
        }
    )
    ffmpeg = which("ffmpeg") and find_ffprobe(FFMPEG_CANDIDATES) or find_ffprobe(FFMPEG_CANDIDATES)
    if which is not shutil.which and which("ffmpeg") is None:
        ffmpeg = None  # an injected resolver (tests) decides; never report a real binary as found
    checks.append(
        {
            "name": "ffmpeg",
            "ok": ffmpeg is not None,
            "detail": ffmpeg
            or "install `ffmpeg@6` (macOS: brew install ffmpeg@6; Spinnaker needs 6)",
        }
    )
    ok, ver = _pyspin()
    checks.append(
        {
            "name": "Spinnaker SDK (PySpin)",
            "ok": ok,
            "detail": ver
            if ok
            else f"not importable ({ver}); run `uv run fri-sdk-check` for the exact "
            f"download for this machine, from {SDK_URL} (free Teledyne account)",
        }
    )
    host, user, password = credentials(dotenv)
    have = bool(host and user and password)
    checks.append(
        {
            "name": "camera credentials (.env)",
            "ok": have,
            "detail": f"{dotenv} has {ENV_HOST}={host}"
            if have
            else f"missing in {dotenv}: run `fri-install` (prompts) or set {ENV_HOST}, {ENV_USER}, "
            f"{ENV_PASSWORD}; without them the visible camera is disabled (thermal still works)",
        }
    )
    return {
        "platform": platform.platform(),
        "backend_dir": str(backend_dir),
        "checks": checks,
        "ok": all(c["ok"] for c in checks),
    }


def print_doctor(rep: dict[str, Any]) -> None:
    print(f"Operator doctor ({rep['platform']})")
    for c in rep["checks"]:
        print(f"  [{'ok' if c['ok'] else 'MISSING'}] {c['name']}: {c['detail']}")
    print(
        "  all prerequisites present" if rep["ok"] else "  fix the MISSING items above, then re-run"
    )


def install_launchd(
    backend_dir: Path, *, port: int, site_origin: str, run: Callable[..., Any]
) -> Path:
    uv = shutil.which("uv") or "/opt/homebrew/bin/uv"
    agents = Path.home() / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    plist = agents / f"{LABEL}.plist"
    plist.write_bytes(
        launchd_plist(uv=uv, backend_dir=backend_dir, port=port, site_origin=site_origin)
    )
    uid = os.getuid()
    run(["launchctl", "bootout", f"gui/{uid}", str(plist)], check=False, capture_output=True)
    run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)], check=True)
    run(["launchctl", "kickstart", "-k", f"gui/{uid}/{LABEL}"], check=False, capture_output=True)
    return plist


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="fri-install", description=__doc__.splitlines()[0])
    p.add_argument("--doctor", action="store_true", help="only report prerequisites")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--site-origin", default=DEFAULT_SITE_ORIGIN)
    p.add_argument(
        "--no-service", action="store_true", help="write .env only, no background service"
    )
    p.add_argument("--host", help="camera IP (skips the prompt)")
    p.add_argument("--rtsp-user", help="RTSP user (skips the prompt)")
    a = p.parse_args(argv)
    backend_dir = Path(__file__).resolve().parent.parent
    dotenv = backend_dir / ".env"
    if a.doctor:
        print_doctor(doctor(backend_dir=backend_dir, dotenv=dotenv))
        return 0
    host, user, existing_pw = credentials(dotenv)
    host = (
        a.host
        or input(f"Camera IP [{host or LAB_CAMERA_HOST}]: ").strip()
        or host
        or LAB_CAMERA_HOST
    )
    user = (
        a.rtsp_user
        or input(f"RTSP user [{user or LAB_RTSP_USER}]: ").strip()
        or user
        or LAB_RTSP_USER
    )
    hint = "Enter = keep current" if existing_pw else "Enter = lab default"
    entered = getpass.getpass(f"RTSP password [{hint}]: ")
    # Empty means "accept the default": the lab password if none is stored, else what is already
    # in .env. So a labmate can press Enter through every prompt and get a working install.
    password = entered or existing_pw or LAB_RTSP_PASSWORD
    write_env(dotenv, host=host, user=user, password=password)
    print(f"wrote {dotenv} (mode 600, git-ignored)")
    if not a.no_service:
        if sys.platform == "darwin":
            plist = install_launchd(
                backend_dir, port=a.port, site_origin=a.site_origin, run=subprocess.run
            )
            print(f"installed and started LaunchAgent {plist}")
            print(f"operator: http://127.0.0.1:{a.port}/api/health")
            print(f"log: {backend_dir / 'operator.log'}")
        elif sys.platform.startswith("linux"):
            try:
                unit = install_systemd(
                    backend_dir, port=a.port, site_origin=a.site_origin, run=subprocess.run
                )
                print(f"installed and started systemd --user service {unit}")
                print(f"operator: http://127.0.0.1:{a.port}/api/health")
                print("logs: journalctl --user -u fri-operator -f")
            except Exception as exc:  # noqa: BLE001 - a headless/no-systemd box must still finish
                print(
                    f"could not install the systemd service ({exc}); run the operator directly "
                    f"with `uv run fri-serve --port {a.port}` or see docs/installation.md"
                )
        else:
            print(
                "background service: automated on macOS (launchd) and Linux (systemd --user); "
                "on Windows see docs/installation.md for Task Scheduler"
            )
    print_doctor(doctor(backend_dir=backend_dir, dotenv=dotenv))
    print(f"then open {a.site_origin}/flir-research-interface/ and enter http://127.0.0.1:{a.port}")
    return 0


__all__ = [
    "LAB_CAMERA_HOST",
    "LAB_RTSP_PASSWORD",
    "LAB_RTSP_USER",
    "LABEL",
    "doctor",
    "install_launchd",
    "install_systemd",
    "launchd_plist",
    "main",
    "systemd_unit",
    "write_env",
]
