"""Open an experiment folder in the OS file manager (spec §5). Local-operator feature.

Windows branch untested on real hardware as of 2026-09-01.
"""

from __future__ import annotations

import logging
import platform
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

Runner = Callable[[list[str]], int]


def reveal_command(system: str, path: Path) -> list[str]:
    if system == "Darwin":
        return ["open", "-R", str(path)]
    if system == "Windows":
        # Separate argv element (not "/select,<path>" concatenated) survives quoting when the
        # path contains spaces.
        return ["explorer", "/select,", str(path)]
    if system == "Linux":
        return ["xdg-open", str(path)]
    raise ValueError(f"no file manager integration for {system!r}")


def contained(root: Path, path: Path) -> bool:
    """True if ``path`` exists and resolves inside ``root``."""
    try:
        root_r = root.resolve(strict=True)
        path_r = path.resolve(strict=True)
    except OSError:
        return False
    return path_r == root_r or root_r in path_r.parents


def _default_runner(cmd: list[str]) -> int:
    try:
        return subprocess.run(cmd, check=False, timeout=10, capture_output=True).returncode
    except (OSError, subprocess.TimeoutExpired):
        return 127


def reveal(
    path: Path, *, system: str | None = None, runner: Runner | None = None
) -> dict[str, Any]:
    runner = runner if runner is not None else _default_runner
    system = system or platform.system()
    try:
        cmd = reveal_command(system, path)
    except ValueError as exc:
        return {"ok": False, "path": str(path), "error": str(exc)}
    logger.info("reveal: %s", cmd)
    rc = runner(cmd)
    # Explorer is known to return a non-zero exit code even when it successfully opens
    # (spec §5), so a non-zero rc from `explorer` is not treated as failure.
    if rc != 0 and cmd[0] != "explorer":
        logger.warning("reveal failed rc=%s cmd=%s", rc, cmd)
        return {"ok": False, "path": str(path), "error": f"{cmd[0]} exited with {rc}"}
    return {"ok": True, "path": str(path), "command": cmd}


__all__ = ["Runner", "contained", "reveal", "reveal_command"]
