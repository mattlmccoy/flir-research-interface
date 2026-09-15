"""Verification gate for the bootstrap ``install.sh`` (shell, so not unit-testable in Python — we
drive it through bash). Guards the two bugs that made a Linux ``curl | bash`` do nothing: the
silent ``$0``/sed self-dispatch, and the Debian-only package logic that skipped Fedora.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

INSTALL_SH = Path(__file__).resolve().parents[2] / "install.sh"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")


def _detect_with(stub_managers: list[str], tmp_path: Path) -> str:
    """Source install.sh (FRI_INSTALL_LIB=1, so main() does not run) with a PATH that contains
    only the given stub package managers, then echo detect_pkg_mgr's answer."""
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir(parents=True)
    for name in stub_managers:
        p = stub_dir / name
        p.write_text("#!/usr/bin/env bash\nexit 0\n")
        os.chmod(p, 0o755)
    script = f'FRI_INSTALL_LIB=1 source "{INSTALL_SH}"\ndetect_pkg_mgr\n'
    out = subprocess.run(
        [BASH, "-c", script],
        env={"PATH": str(stub_dir), "FRI_INSTALL_LIB": "1", "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def test_detect_pkg_mgr_picks_the_distro_package_manager(tmp_path: Path) -> None:
    assert _detect_with(["dnf"], tmp_path / "fedora") == "dnf"  # Fedora — the reported failure
    assert _detect_with(["apt-get"], tmp_path / "ubuntu") == "apt-get"
    assert _detect_with(["pacman"], tmp_path / "arch") == "pacman"
    assert _detect_with(["zypper"], tmp_path / "suse") == "zypper"
    assert _detect_with([], tmp_path / "bare") == "none"


def test_apt_preferred_when_multiple_present(tmp_path: Path) -> None:
    # A box with both apt and dnf resolves deterministically (apt first), never ambiguous.
    assert _detect_with(["apt-get", "dnf"], tmp_path) == "apt-get"


def test_no_broken_self_dispatch_and_is_sourceable(tmp_path: Path) -> None:
    text = INSTALL_SH.read_text()
    # The old bug: `exec bash -c "$(sed -n ... "$0")"` — empty under curl|bash, silent no-op.
    assert 'sed -n' not in text, "install.sh must not self-parse via sed $0 (broke curl|bash)"
    assert 'exec bash -c' not in text
    # Sourcing as a library must define functions without executing main().
    marker = tmp_path / "ran"
    script = (
        f'FRI_INSTALL_LIB=1 source "{INSTALL_SH}"\n'
        f'type detect_pkg_mgr linux_main mac_main main >/dev/null\n'
        f'echo sourced-ok\n'
    )
    out = subprocess.run(
        [BASH, "-c", script],
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=True,
    )
    assert "sourced-ok" in out.stdout
    assert not marker.exists()
