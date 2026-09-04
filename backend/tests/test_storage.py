"""External-drive storage: detection filter, registered-drive config, verify + move."""

from __future__ import annotations

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
