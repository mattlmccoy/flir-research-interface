#!/usr/bin/env python3
"""Clear the executable-stack flag on the given ELF shared objects.

Used by install.sh on hardened Linux (Fedora/SELinux): FLIR's libSpinnaker.so / libSpinVideo.so are
marked PT_GNU_STACK = RWX, which such kernels refuse to load. Runs under the SYSTEM python3 as root
(it only needs the standard library), so it works even though the operator's uv venv is elsewhere.

    sudo python3 scripts/clear_execstack.py /opt/spinnaker/lib/*.so*
"""

from __future__ import annotations

import sys
from pathlib import Path

# Import the shared, unit-tested implementation from the checkout's backend package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from flir_research_interface.elf import clear_gnu_stack_exec_files  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    changed = clear_gnu_stack_exec_files(list(args))
    if changed:
        print(f"cleared executable stack on {len(changed)} library file(s):")
        for name in changed:
            print(f"  {name}")
    else:
        print("no executable-stack flags to clear")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
