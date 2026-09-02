"""Open an experiment folder in the OS file manager (spec §5). Local-operator feature."""

from __future__ import annotations

import platform
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

Runner = Callable[[list[str]], int]


def reveal_command(system: str, path: Path) -> list[str]:
    if system == "Darwin":
        return ["open", "-R", str(path)]
    if system == "Windows":
        return ["explorer", f"/select,{path}"]
    if system == "Linux":
        return ["xdg-open", str(path.parent)]
    raise ValueError(f"no file manager integration for {system!r}")


def contained(root: Path, path: Path) -> bool:
    """True if ``path`` exists, is not a symlink, and resolves inside ``root``."""
    if path.is_symlink():
        return False
    try:
        root_r = root.resolve(strict=True)
        path_r = path.resolve(strict=True)
    except OSError:
        return False
    return path_r == root_r or root_r in path_r.parents


def _default_runner(cmd: list[str]) -> int:
    try:
        return subprocess.run(cmd, check=False, timeout=10).returncode
    except (OSError, subprocess.TimeoutExpired):
        return 127


def reveal(
    path: Path, *, system: str | None = None, runner: Runner = _default_runner
) -> dict[str, Any]:
    system = system or platform.system()
    try:
        cmd = reveal_command(system, path)
    except ValueError as exc:
        return {"ok": False, "path": str(path), "error": str(exc)}
    rc = runner(cmd)
    if rc != 0:
        return {"ok": False, "path": str(path), "error": f"{cmd[0]} exited with {rc}"}
    return {"ok": True, "path": str(path), "command": cmd}


__all__ = ["Runner", "contained", "reveal", "reveal_command"]
