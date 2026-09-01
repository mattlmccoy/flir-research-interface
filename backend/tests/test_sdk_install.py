"""Tests for the Spinnaker/PySpin artifact selector (platform -> which file to install)."""

from __future__ import annotations

import pytest

from flir_research_interface.sdk_install import (
    SPINNAKER_VERSION,
    Selection,
    select_artifacts,
)


def test_macos_apple_silicon_py312_points_at_bundled_wheel_tarball() -> None:
    sel = select_artifacts(system="Darwin", machine="arm64", python=(3, 12))
    assert isinstance(sel, Selection)
    assert sel.supported is True
    assert sel.sdk_artifact_hint.startswith("Spinnaker") and "macOS" in sel.sdk_artifact_hint
    assert (
        sel.pyspin_glob == f"spinnaker_python-{SPINNAKER_VERSION}-cp312-cp312-macosx_*_arm64.tar.gz"
    )
    assert "/Applications/Spinnaker/PySpin" in sel.pyspin_search_dirs
    assert any("ffmpeg@6" in step for step in sel.steps)


def test_macos_intel_is_not_supported_by_spinnaker_4() -> None:
    sel = select_artifacts(system="Darwin", machine="x86_64", python=(3, 12))
    assert sel.supported is False
    assert "3.2" in sel.reason  # Teledyne: Intel Macs must use Spinnaker 3.2


def test_linux_jammy_amd64_py310() -> None:
    sel = select_artifacts(system="Linux", machine="x86_64", python=(3, 10), linux_codename="jammy")
    assert sel.supported is True
    assert sel.sdk_glob == f"spinnaker-{SPINNAKER_VERSION}-jammy-amd64-pkg.tar.gz"
    assert (
        sel.pyspin_glob == f"spinnaker_python-{SPINNAKER_VERSION}-cp310-cp310-linux_x86_64.tar.gz"
    )


def test_linux_arm64_maps_machine_names() -> None:
    sel = select_artifacts(
        system="Linux", machine="aarch64", python=(3, 12), linux_codename="noble"
    )
    assert sel.sdk_glob == f"spinnaker-{SPINNAKER_VERSION}-noble-arm64-pkg.tar.gz"
    assert (
        sel.pyspin_glob == f"spinnaker_python-{SPINNAKER_VERSION}-cp312-cp312-linux_aarch64.tar.gz"
    )


def test_windows_x64() -> None:
    sel = select_artifacts(system="Windows", machine="AMD64", python=(3, 11))
    assert sel.supported is True
    assert sel.sdk_glob == f"SpinnakerSDK_FULL_{SPINNAKER_VERSION}_x64.exe"
    assert sel.pyspin_glob == f"spinnaker_python-{SPINNAKER_VERSION}-cp311-cp311-win_amd64.*"


@pytest.mark.parametrize("python", [(3, 9), (3, 13), (3, 14)])
def test_unsupported_python_versions_are_refused(python: tuple[int, int]) -> None:
    sel = select_artifacts(system="Darwin", machine="arm64", python=python)
    assert sel.supported is False
    assert "3.10" in sel.reason and "3.12" in sel.reason


def test_local_match_is_reported_when_a_file_matches_the_glob() -> None:
    sel = select_artifacts(
        system="Linux",
        machine="aarch64",
        python=(3, 12),
        linux_codename="focal",
        local_files=[
            "vendor/spinnaker/spinnaker-4.4.0.246-focal-arm64-pkg.tar.gz",
            "vendor/spinnaker/spinnaker_python-4.4.0.246-cp312-cp312-linux_aarch64.tar.gz",
            "vendor/spinnaker/SpinnakerSDK_FULL_4.4.0.246_x64.exe",
        ],
    )
    assert sel.sdk_local == "vendor/spinnaker/spinnaker-4.4.0.246-focal-arm64-pkg.tar.gz"
    assert (
        sel.pyspin_local
        == "vendor/spinnaker/spinnaker_python-4.4.0.246-cp312-cp312-linux_aarch64.tar.gz"
    )


def test_no_local_match_yields_none_and_download_instruction() -> None:
    sel = select_artifacts(system="Windows", machine="AMD64", python=(3, 12), local_files=[])
    assert sel.sdk_local is None and sel.pyspin_local is None
    assert any("teledynevisionsolutions.com" in step for step in sel.steps)
