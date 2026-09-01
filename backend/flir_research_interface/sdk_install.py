"""Spinnaker SDK / PySpin artifact selection for the current machine.

FLIR's Spinnaker EULA (§3) forbids copying or disclosing the SDK to third parties, so this
project never redistributes installers or wheels. Instead this module tells a user exactly
which Teledyne artifact their machine needs, where an already-downloaded copy might be
(a local ``vendor/spinnaker/`` folder, or the wheels bundled inside the macOS installer at
``/Applications/Spinnaker/PySpin``), and the documented install steps.

Naming conventions were taken from real 4.4.0.246 downloads observed on 2026-09-01:

* Windows:  ``SpinnakerSDK_FULL_<ver>_x64.exe``;
            PySpin ``spinnaker_python-<ver>-cp3XX-cp3XX-win_amd64.*``
* Linux:    ``spinnaker-<ver>-<codename>-<amd64|arm64>-pkg.tar.gz``;
            PySpin ``spinnaker_python-<ver>-cp3XX-cp3XX-linux_<x86_64|aarch64>.tar.gz``
* macOS:    a ``.dmg`` (the .pkg inside installs to /Applications/Spinnaker);
            PySpin ``spinnaker_python-<ver>-cp3XX-cp3XX-macosx_<ver>_arm64.tar.gz`` **inside the
            installer**, not a separate download. Apple Silicon only (Intel Macs: Spinnaker 3.2).
"""

from __future__ import annotations

import fnmatch
import os
import platform
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

SPINNAKER_VERSION = "4.4.0.246"
SUPPORTED_PYTHON: tuple[tuple[int, int], ...] = ((3, 10), (3, 11), (3, 12))
DOWNLOAD_URL = "https://www.teledynevisionsolutions.com/products/spinnaker-sdk/"
MACOS_PYSPIN_DIR = "/Applications/Spinnaker/PySpin"
DEFAULT_VENDOR_DIR = "vendor/spinnaker"

_LINUX_ARCH = {
    "x86_64": ("amd64", "x86_64"),
    "amd64": ("amd64", "x86_64"),
    "aarch64": ("arm64", "aarch64"),
    "arm64": ("arm64", "aarch64"),
}


@dataclass(frozen=True)
class Selection:
    """What to install on this machine, and where a local copy may already be."""

    supported: bool
    reason: str
    system: str
    machine: str
    python_tag: str
    sdk_artifact_hint: str
    sdk_glob: str | None
    pyspin_glob: str | None
    pyspin_search_dirs: tuple[str, ...]
    sdk_local: str | None
    pyspin_local: str | None
    steps: tuple[str, ...] = field(default_factory=tuple)


def _match(glob: str | None, files: Iterable[str]) -> str | None:
    if glob is None:
        return None
    for f in files:
        if fnmatch.fnmatch(os.path.basename(f), glob):
            return f
    return None


def select_artifacts(
    *,
    system: str,
    machine: str,
    python: tuple[int, int],
    linux_codename: str | None = None,
    local_files: Sequence[str] = (),
    vendor_dir: str = DEFAULT_VENDOR_DIR,
) -> Selection:
    """Pure function: platform facts in, install guidance out. No filesystem access."""
    py_tag = f"cp{python[0]}{python[1]}"
    common = dict(system=system, machine=machine, python_tag=py_tag)
    py_list = ", ".join(f"{a}.{b}" for a, b in SUPPORTED_PYTHON)

    if python not in SUPPORTED_PYTHON:
        return Selection(
            supported=False,
            reason=f"PySpin {SPINNAKER_VERSION} ships wheels for Python {py_list} only "
            f"(3.9 and older deprecated); you are on {python[0]}.{python[1]}. Recreate the venv, "
            f"e.g. `uv venv --python 3.12 .venv`.",
            sdk_artifact_hint="",
            sdk_glob=None,
            pyspin_glob=None,
            pyspin_search_dirs=(),
            sdk_local=None,
            pyspin_local=None,
            steps=(),
            **common,
        )

    if system == "Darwin":
        if machine != "arm64":
            return Selection(
                supported=False,
                reason="Spinnaker 4.x has no Intel-Mac build; Teledyne directs Intel Macs to "
                "Spinnaker 3.2 (macOS <= 11.6), whose PySpin targets Python <= 3.8. "
                "Use an Apple Silicon Mac, Linux, or Windows for the acquisition machine.",
                sdk_artifact_hint="",
                sdk_glob=None,
                pyspin_glob=None,
                pyspin_search_dirs=(),
                sdk_local=None,
                pyspin_local=None,
                steps=(),
                **common,
            )
        pyspin_glob = (
            f"spinnaker_python-{SPINNAKER_VERSION}-{py_tag}-{py_tag}-macosx_*_arm64.tar.gz"
        )
        search = (MACOS_PYSPIN_DIR, vendor_dir)
        steps: tuple[str, ...] = (
            "brew install pkg-config libomp libusb ffmpeg@6   # newer ffmpeg fails (README)",
            f"Install the Spinnaker {SPINNAKER_VERSION} macOS (Apple Silicon) .pkg from the DMG "
            f"downloaded at {DOWNLOAD_URL}",
            "The PySpin wheel is NOT a separate download: extract "
            f"{MACOS_PYSPIN_DIR}/{pyspin_glob}",
            "uv pip install <extracted>/"
            f"spinnaker_python-{SPINNAKER_VERSION}-{py_tag}-{py_tag}-macosx_*_arm64.whl",
        )
        return Selection(
            supported=True,
            reason="Apple Silicon macOS is supported by Spinnaker 4.1+.",
            sdk_artifact_hint=f"Spinnaker {SPINNAKER_VERSION} macOS Apple Silicon .dmg/.pkg",
            sdk_glob="Spinnaker*.dmg",
            pyspin_glob=pyspin_glob,
            pyspin_search_dirs=search,
            sdk_local=_match("Spinnaker*.dmg", local_files),
            pyspin_local=_match(pyspin_glob, local_files),
            steps=steps,
            **common,
        )

    if system == "Linux":
        arch = _LINUX_ARCH.get(machine.lower())
        if arch is None:
            return Selection(
                supported=False,
                reason=f"unrecognised Linux machine type {machine!r}",
                sdk_artifact_hint="",
                sdk_glob=None,
                pyspin_glob=None,
                pyspin_search_dirs=(),
                sdk_local=None,
                pyspin_local=None,
                steps=(),
                **common,
            )
        deb_arch, wheel_arch = arch
        codename = linux_codename or "*"
        sdk_glob = f"spinnaker-{SPINNAKER_VERSION}-{codename}-{deb_arch}-pkg.tar.gz"
        pyspin_glob = (
            f"spinnaker_python-{SPINNAKER_VERSION}-{py_tag}-{py_tag}-linux_{wheel_arch}.tar.gz"
        )
        steps = (
            f"Download {sdk_glob} and {pyspin_glob} from {DOWNLOAD_URL} (Ubuntu focal/jammy/noble)",
            f"tar -xzf {sdk_glob} && cd spinnaker-{SPINNAKER_VERSION}-{deb_arch} "
            "&& sudo sh install_spinnaker.sh",
            f"tar -xzf {pyspin_glob} && uv pip install "
            f"spinnaker_python-{SPINNAKER_VERSION}-{py_tag}-{py_tag}-linux_{wheel_arch}.whl",
        )
        return Selection(
            supported=True,
            reason="Ubuntu 20.04/22.04/24.04 amd64 and arm64 are supported.",
            sdk_artifact_hint=f"Spinnaker {SPINNAKER_VERSION} Ubuntu {codename} {deb_arch} .tar.gz",
            sdk_glob=sdk_glob,
            pyspin_glob=pyspin_glob,
            pyspin_search_dirs=(vendor_dir,),
            sdk_local=_match(sdk_glob, local_files),
            pyspin_local=_match(pyspin_glob, local_files),
            steps=steps,
            **common,
        )

    if system == "Windows":
        sdk_glob = f"SpinnakerSDK_FULL_{SPINNAKER_VERSION}_x64.exe"
        pyspin_glob = f"spinnaker_python-{SPINNAKER_VERSION}-{py_tag}-{py_tag}-win_amd64.*"
        steps = (
            f"Download {sdk_glob} and the PySpin {py_tag} win_amd64 package from {DOWNLOAD_URL}",
            f"Run {sdk_glob} (Windows 11 x64; Windows 10 deprecated by Teledyne)",
            f"uv pip install spinnaker_python-{SPINNAKER_VERSION}-{py_tag}-{py_tag}-win_amd64.whl",
        )
        return Selection(
            supported=True,
            reason="Windows 11 x64 is supported.",
            sdk_artifact_hint=f"Spinnaker {SPINNAKER_VERSION} Windows x64 installer",
            sdk_glob=sdk_glob,
            pyspin_glob=pyspin_glob,
            pyspin_search_dirs=(vendor_dir,),
            sdk_local=_match(sdk_glob, local_files),
            pyspin_local=_match(pyspin_glob, local_files),
            steps=steps,
            **common,
        )

    return Selection(
        supported=False,
        reason=f"unsupported operating system {system!r}",
        sdk_artifact_hint="",
        sdk_glob=None,
        pyspin_glob=None,
        pyspin_search_dirs=(),
        sdk_local=None,
        pyspin_local=None,
        steps=(),
        **common,
    )


def _linux_codename() -> str | None:
    try:
        with open("/etc/os-release", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VERSION_CODENAME="):
                    return line.split("=", 1)[1].strip().strip('"') or None
    except OSError:
        return None
    return None


def detect_and_select(vendor_dir: str = DEFAULT_VENDOR_DIR) -> Selection:
    """Detect this machine and scan ``vendor_dir`` (+ macOS bundled dir) for local artifacts."""
    search_dirs = [vendor_dir]
    if platform.system() == "Darwin":
        search_dirs.append(MACOS_PYSPIN_DIR)
    local: list[str] = []
    for d in search_dirs:
        if os.path.isdir(d):
            local.extend(os.path.join(d, f) for f in sorted(os.listdir(d)))
    return select_artifacts(
        system=platform.system(),
        machine=platform.machine(),
        python=(sys.version_info.major, sys.version_info.minor),
        linux_codename=_linux_codename() if platform.system() == "Linux" else None,
        local_files=local,
        vendor_dir=vendor_dir,
    )


def pyspin_importable() -> tuple[bool, str]:
    """Try ``import PySpin`` and report the Spinnaker library version or the failure text."""
    try:
        import PySpin  # noqa: N813

        system = PySpin.System.GetInstance()
        try:
            v = system.GetLibraryVersion()
            return True, f"{v.major}.{v.minor}.{v.type}.{v.build}"
        finally:
            system.ReleaseInstance()
    except Exception as exc:  # noqa: BLE001 - report anything (ImportError, dlopen failure)
        return False, f"{type(exc).__name__}: {exc}"


def main(argv: list[str] | None = None) -> int:
    """CLI: ``fri-sdk-check`` prints what this machine needs and whether PySpin already works."""
    sel = detect_and_select()
    ok, detail = pyspin_importable()
    print(f"Machine: {sel.system} {sel.machine}, Python {sel.python_tag}")
    print(f"PySpin importable: {ok}  ({detail})")
    if ok:
        return 0
    print(f"Supported: {sel.supported}. {sel.reason}")
    if sel.supported:
        print(f"SDK artifact:    {sel.sdk_artifact_hint}")
        print(f"  local copy:    {sel.sdk_local or 'not found'}")
        print(f"PySpin artifact: {sel.pyspin_glob}")
        searched = ", ".join(sel.pyspin_search_dirs)
        print(f"  local copy:    {sel.pyspin_local or 'not found'}  (searched {searched})")
        print("Steps:")
        for i, step in enumerate(sel.steps, 1):
            print(f"  {i}. {step}")
    return 1


__all__ = [
    "DOWNLOAD_URL",
    "MACOS_PYSPIN_DIR",
    "SPINNAKER_VERSION",
    "SUPPORTED_PYTHON",
    "Selection",
    "detect_and_select",
    "pyspin_importable",
    "select_artifacts",
]
