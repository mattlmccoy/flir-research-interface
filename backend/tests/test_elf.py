"""Clearing the executable-stack flag on the Spinnaker libraries.

FLIR's prebuilt libSpinnaker.so / libSpinVideo.so are marked PT_GNU_STACK = RWX. Debian/Ubuntu
loads them, but a hardened Fedora/SELinux kernel refuses with "cannot enable executable stack as
shared object requires", so `import PySpin` fails. We clear the executable bit in place (stdlib
only, so it can run under the system python3 as root during install).
"""

from __future__ import annotations

import struct
from pathlib import Path

from flir_research_interface.elf import PT_GNU_STACK, clear_gnu_stack_exec


def _minimal_elf64(stack_flags: int) -> bytes:
    """A tiny but valid-enough ELF64 (little-endian) with a single PT_GNU_STACK program header."""
    e_phoff = 64
    header = struct.pack(
        "<4sBBBB8xHHIQQQIHHHHHH",
        b"\x7fELF", 2, 1, 1, 0,  # magic, class=64, data=LE, version, osabi
        3, 0x3E, 1,  # e_type=ET_DYN, e_machine=x86-64, e_version
        0, e_phoff, 0, 0,  # e_entry, e_phoff, e_shoff, e_flags
        64, 56, 1,  # e_ehsize, e_phentsize, e_phnum
        0, 0, 0,  # e_shentsize, e_shnum, e_shstrndx
    )
    phdr = struct.pack("<IIQQQQQQ", PT_GNU_STACK, stack_flags, 0, 0, 0, 0, 0, 0)
    return header + phdr


def _stack_flags(path: Path) -> int:
    d = path.read_bytes()
    e_phoff = struct.unpack_from("<Q", d, 0x20)[0]
    ps = struct.unpack_from("<H", d, 0x36)[0]
    pn = struct.unpack_from("<H", d, 0x38)[0]
    for i in range(pn):
        off = e_phoff + i * ps
        if struct.unpack_from("<I", d, off)[0] == PT_GNU_STACK:
            return struct.unpack_from("<I", d, off + 4)[0]
    raise AssertionError("no PT_GNU_STACK")


def test_clears_executable_stack_and_is_idempotent(tmp_path: Path) -> None:
    lib = tmp_path / "libSpinnaker.so"
    lib.write_bytes(_minimal_elf64(0b111))  # RWX, like the real FLIR libs
    assert clear_gnu_stack_exec(lib) is True  # cleared
    assert _stack_flags(lib) == 0b110  # RW-, X bit gone; R and W preserved
    assert clear_gnu_stack_exec(lib) is False  # nothing left to do


def test_leaves_non_executable_stack_untouched(tmp_path: Path) -> None:
    lib = tmp_path / "libSpinnaker_C.so"
    lib.write_bytes(_minimal_elf64(0b110))  # already RW-
    assert clear_gnu_stack_exec(lib) is False
    assert _stack_flags(lib) == 0b110


def test_ignores_non_elf_files(tmp_path: Path) -> None:
    junk = tmp_path / "notelf.txt"
    junk.write_text("hello")
    assert clear_gnu_stack_exec(junk) is False
