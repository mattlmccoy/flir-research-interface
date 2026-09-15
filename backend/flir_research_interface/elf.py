"""Clear the executable-stack flag (PT_GNU_STACK = RWX) on ELF shared objects.

FLIR's prebuilt libSpinnaker.so / libSpinVideo.so ship with an executable stack. Debian/Ubuntu
loads them, but a hardened Fedora/SELinux kernel refuses (``import PySpin`` -> "cannot enable
executable stack as shared object requires"). Clearing the X bit in the PT_GNU_STACK program header
fixes it without patching the kernel.

Deliberately standard-library only: the installer runs this under the system ``python3`` as root to
patch files under /opt/spinnaker/lib, where the operator's uv venv is not available.
"""

from __future__ import annotations

import struct
from pathlib import Path

PT_GNU_STACK = 0x6474E551
_PF_X = 0x1


def clear_gnu_stack_exec(path: Path | str) -> bool:
    """Clear the executable bit of the PT_GNU_STACK segment of ``path`` in place. Returns True if
    the file was changed, False if it was not an ELF, had no PT_GNU_STACK, or was already clean."""
    path = Path(path)
    try:
        data = bytearray(path.read_bytes())
    except OSError:
        return False
    if data[:4] != b"\x7fELF":
        return False
    is64 = data[4] == 2
    endian = "<" if data[5] == 1 else ">"
    try:
        if is64:
            e_phoff = struct.unpack_from(endian + "Q", data, 0x20)[0]
            e_phentsize = struct.unpack_from(endian + "H", data, 0x36)[0]
            e_phnum = struct.unpack_from(endian + "H", data, 0x38)[0]
            flags_off = 4  # p_flags immediately follows p_type in ELF64
        else:
            e_phoff = struct.unpack_from(endian + "I", data, 0x1C)[0]
            e_phentsize = struct.unpack_from(endian + "H", data, 0x2A)[0]
            e_phnum = struct.unpack_from(endian + "H", data, 0x2C)[0]
            flags_off = 24  # p_flags is the last word of the ELF32 program header
        changed = False
        for i in range(e_phnum):
            off = e_phoff + i * e_phentsize
            if off + e_phentsize > len(data):
                break
            if struct.unpack_from(endian + "I", data, off)[0] != PT_GNU_STACK:
                continue
            fo = off + flags_off
            p_flags = struct.unpack_from(endian + "I", data, fo)[0]
            if p_flags & _PF_X:
                struct.pack_into(endian + "I", data, fo, p_flags & ~_PF_X)
                changed = True
        if changed:
            path.write_bytes(bytes(data))
        return changed
    except struct.error:
        return False


def clear_gnu_stack_exec_files(paths: list[Path | str]) -> list[str]:
    """Clear the executable stack on each path; return the names of the files actually changed."""
    return [str(p) for p in paths if clear_gnu_stack_exec(p)]


__all__ = ["PT_GNU_STACK", "clear_gnu_stack_exec", "clear_gnu_stack_exec_files"]
