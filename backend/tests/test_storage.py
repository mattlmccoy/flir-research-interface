"""External-drive storage: detection filter, registered-drive config, verify + move."""

from __future__ import annotations

from pathlib import Path

import pytest

from flir_research_interface.storage import _Part, selectable_drives

# Captured from psutil.disk_partitions(all=False) on macOS (see the design spec): the enumeration
# is dominated by system volumes + read-only mounted DMGs that must be filtered out.
MAC_PARTS = [
    _Part("/dev/disk3s1s1", "/", "apfs", "ro,local,rootfs"),
    _Part("/dev/disk3s5", "/System/Volumes/Data", "apfs", "rw,local"),
    _Part("/dev/disk19s1", "/Volumes/Spinnaker 4.4.0.246", "apfs", "ro,nosuid,local"),  # a dmg
    _Part("/dev/diskX", "/Volumes/FieldData", "exfat", "rw,nosuid,local"),  # a real USB drive
]


def test_mac_keeps_only_real_writable_external_volumes() -> None:
    usage = {"/Volumes/FieldData": (2_000_000_000_000, 1_500_000_000_000)}  # (total, free)
    drives = selectable_drives("darwin", MAC_PARTS, usage.__getitem__)
    assert [d["mount"] for d in drives] == ["/Volumes/FieldData"]
    d = drives[0]
    assert d["label"] == "FieldData"
    assert d["free_bytes"] == 1_500_000_000_000 and d["total_bytes"] == 2_000_000_000_000


def test_linux_keeps_media_mnt_only() -> None:
    parts = [
        _Part("/dev/sda2", "/", "ext4", "rw"),
        _Part("/dev/sdb1", "/media/matt/Field", "exfat", "rw"),
        _Part("/dev/sdc1", "/mnt/ro", "ext4", "ro"),  # read-only → excluded
    ]
    mounts = [d["mount"] for d in selectable_drives("linux", parts, lambda m: (10**12, 10**11))]
    assert mounts == ["/media/matt/Field"]


def test_darwin_excludes_boot_volume_and_read_only() -> None:
    parts = [
        _Part("/dev/d1", "/Volumes/Macintosh HD", "apfs", "rw,local"),  # boot volume alias
        _Part("/dev/d2", "/Volumes/Backup", "hfs", "ro,local"),  # read-only
    ]
    assert selectable_drives("darwin", parts, lambda m: (10**12, 10**11)) == []


def test_storage_config_round_trip_and_absent_default(tmp_path: Path) -> None:
    from flir_research_interface.storage import load_storage_config, save_storage_config

    assert load_storage_config(tmp_path) == {"drive": None}
    save_storage_config(
        tmp_path, {"drive": {"mount": "/Volumes/F", "root": "/Volumes/F/FLIR-recordings"}}
    )
    assert load_storage_config(tmp_path)["drive"]["mount"] == "/Volumes/F"


def test_register_drive_creates_folder_and_persists(tmp_path: Path) -> None:
    from flir_research_interface.storage import DRIVE_SUBDIR, load_storage_config, register_drive

    local = tmp_path / "local"
    local.mkdir()
    drive = tmp_path / "FieldData"
    drive.mkdir()
    cfg = register_drive(local, str(drive))
    assert cfg["drive"]["root"] == str(drive / DRIVE_SUBDIR)
    assert (drive / DRIVE_SUBDIR).is_dir()
    assert load_storage_config(local)["drive"]["mount"] == str(drive)  # persisted
    with pytest.raises(ValueError):  # a path we cannot create/write raises
        register_drive(local, "/nonexistent/xyz-should-not-exist")


def test_forget_drive_clears_config_without_touching_files(tmp_path: Path) -> None:
    from flir_research_interface.storage import (
        DRIVE_SUBDIR,
        forget_drive,
        load_storage_config,
        register_drive,
    )

    local = tmp_path / "local"
    local.mkdir()
    drive = tmp_path / "FieldData"
    drive.mkdir()
    register_drive(local, str(drive))
    forget_drive(local)
    assert load_storage_config(local) == {"drive": None}
    assert (drive / DRIVE_SUBDIR).is_dir()  # files left in place


def test_verify_copy_ok_and_detects_size_and_content_mismatch(tmp_path: Path) -> None:
    from flir_research_interface.storage import verify_copy

    src = tmp_path / "a"
    dst = tmp_path / "b"
    for d in (src, dst):
        (d / "sub").mkdir(parents=True)
        (d / "metadata.json").write_text('{"x":1}')
        (d / "sub" / "chunk").write_bytes(b"0123456789")
    assert verify_copy(src, dst) is None  # identical → OK

    (dst / "sub" / "chunk").write_bytes(b"012345678")  # size differs
    assert "chunk" in (verify_copy(src, dst) or "")

    (dst / "sub" / "chunk").write_bytes(b"0123456789")  # restore size
    (dst / "metadata.json").write_text('{"x":2}')  # same size, different bytes
    assert "metadata.json" in (verify_copy(src, dst) or "")

    (dst / "metadata.json").write_text('{"x":1}')
    (dst / "sub" / "chunk").unlink()  # missing file
    assert "chunk" in (verify_copy(src, dst) or "")
