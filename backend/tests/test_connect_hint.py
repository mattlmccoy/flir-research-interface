"""Plain-language connect errors: subnet overlap (Spinnaker -1023) and a vanished adapter (-1024).

Fixtures in tests/fixtures/neterr/ are real captures from the lab Mac on 2026-10-27 (see the
fixtures README). ``ifconfig_now.txt`` was taken AFTER Matt fixed the conflict, so en15 is /24
in it. The conflicting state was observed live as
``en15: inet 192.168.9.1 netmask 0xffff0000 broadcast 192.168.255.255``; the conflict tests
rebuild it by changing only that one line of the capture (``_conflict_ifaces``).
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path

from flir_research_interface.net_diagnostics import (
    IfaceAddr,
    explain_camera_error,
    overlapping_subnets,
    parse_hardware_ports,
)

FIX = Path(__file__).parent / "fixtures" / "neterr"
_FIXED_EN15 = "inet 192.168.9.1 netmask 0xffffff00 broadcast 192.168.9.255"
_LIVE_CONFLICT_EN15 = "inet 192.168.9.1 netmask 0xffff0000 broadcast 192.168.255.255"


def _raw_1023() -> str:
    """The exact error text from the captured operator log (attempt 1/4)."""
    line = (FIX / "spinnaker_1023_log.txt").read_text().splitlines()[0]
    m = re.search(r"failed \((.*)\); retrying", line)
    assert m
    return m.group(1)


def _raw_1024() -> str:
    line = next(ln for ln in (FIX / "spinnaker_1023_log.txt").read_text().splitlines()
                if "[-1024]" in ln)
    return line.split("disconnect: ", 1)[1]


def _parse_ifconfig(text: str) -> list[IfaceAddr]:
    """Test-side reader of ``ifconfig`` text into (dev, ip, prefix); the operator uses psutil.
    Loopback is skipped, as gvcp.host_interfaces() does."""
    out: list[IfaceAddr] = []
    dev = ""
    for line in text.splitlines():
        head = re.match(r"^(\S+): flags=", line)
        if head:
            dev = head.group(1)
            continue
        m = re.match(r"^\s+inet (\S+) netmask 0x([0-9a-f]+)", line)
        if m and not m.group(1).startswith("127."):
            out.append(IfaceAddr(dev, m.group(1), bin(int(m.group(2), 16)).count("1")))
    return out


def _fixed_ifaces() -> list[IfaceAddr]:
    return _parse_ifconfig((FIX / "ifconfig_now.txt").read_text())


def _conflict_ifaces() -> list[IfaceAddr]:
    text = (FIX / "ifconfig_now.txt").read_text()
    assert text.count(_FIXED_EN15) == 1
    return _parse_ifconfig(text.replace(_FIXED_EN15, _LIVE_CONFLICT_EN15))


def _names() -> dict[str, str]:
    return parse_hardware_ports((FIX / "hardwareports.txt").read_text())


# -- parse_hardware_ports -------------------------------------------------------------------------


def test_hardware_ports_map_each_device_to_its_port_name() -> None:
    names = _names()
    assert names["en15"] == "AX88179A"
    assert names["en13"] == "USB 10/100/1000 LAN"
    assert names["en16"] == "AX88772A"
    assert names["en0"] == "Wi-Fi"
    assert names["bridge0"] == "Thunderbolt Bridge"
    assert len(names) == 11  # every "Hardware Port" block; the VLAN footer adds nothing


def test_hardware_ports_tolerates_empty_and_junk_text() -> None:
    assert parse_hardware_ports("") == {}
    assert parse_hardware_ports("Device: en9\nnot a port block\n") == {}


# -- overlapping_subnets --------------------------------------------------------------------------


def test_the_capture_parses_to_the_live_ipv4_adapters() -> None:
    assert _fixed_ifaces() == [
        IfaceAddr("en0", "10.90.39.215", 17),
        IfaceAddr("en16", "192.168.7.108", 24),
        IfaceAddr("en15", "192.168.9.1", 24),
        IfaceAddr("en13", "192.168.8.1", 24),
    ]


def test_no_overlap_after_the_fix() -> None:
    assert overlapping_subnets(_fixed_ifaces()) == []


def test_the_live_slash16_overlaps_both_lab_adapters_wider_first() -> None:
    pairs = overlapping_subnets(_conflict_ifaces())
    assert pairs == [
        (IfaceAddr("en15", "192.168.9.1", 16), IfaceAddr("en16", "192.168.7.108", 24)),
        (IfaceAddr("en15", "192.168.9.1", 16), IfaceAddr("en13", "192.168.8.1", 24)),
    ]


def test_same_subnet_twice_is_an_overlap_but_one_device_is_not() -> None:
    a, b = IfaceAddr("en13", "192.168.7.1", 24), IfaceAddr("en16", "192.168.7.108", 24)
    assert overlapping_subnets([a, b]) == [(a, b)]
    assert overlapping_subnets([a, IfaceAddr("en13", "192.168.7.9", 24)]) == []


def test_malformed_rows_are_skipped() -> None:
    good = IfaceAddr("en13", "192.168.8.1", 24)
    assert overlapping_subnets([IfaceAddr("en9", "not-an-ip", 24), good]) == []


# -- explain_camera_error: -1023 ------------------------------------------------------------------


def test_1023_names_the_wide_adapter_the_camera_adapter_and_the_exact_fix() -> None:
    hint = explain_camera_error(_raw_1023(), _conflict_ifaces(), _names(), camera_ip="192.168.8.2")
    assert hint is not None
    assert hint["kind"] == "subnet_conflict"
    assert hint["message"] == (
        "Camera can't connect: adapter AX88179A (en15) is 192.168.9.1/16, which overlaps the "
        "camera adapter USB 10/100/1000 LAN (en13, 192.168.8.1/24). Narrow it to /24 in Terminal:"
    )
    assert hint["command"] == 'sudo networksetup -setmanual "AX88179A" 192.168.9.1 255.255.255.0'


def test_1023_without_the_camera_ip_lists_every_adapter_it_overlaps() -> None:
    hint = explain_camera_error(_raw_1023(), _conflict_ifaces(), _names(), camera_ip=None)
    assert hint is not None and hint["kind"] == "subnet_conflict"
    assert "AX88179A (en15) is 192.168.9.1/16" in hint["message"]
    assert "AX88772A (en16, 192.168.7.108/24)" in hint["message"]
    assert "USB 10/100/1000 LAN (en13, 192.168.8.1/24)" in hint["message"]
    assert hint["command"] == 'sudo networksetup -setmanual "AX88179A" 192.168.9.1 255.255.255.0'


def test_1023_falls_back_to_the_device_name_when_no_port_name_is_known() -> None:
    hint = explain_camera_error(_raw_1023(), _conflict_ifaces(), {}, camera_ip="192.168.8.2")
    assert hint is not None
    assert "adapter en15 is 192.168.9.1/16" in hint["message"]
    assert hint["command"] == 'sudo networksetup -setmanual "en15" 192.168.9.1 255.255.255.0'


def test_1023_with_no_visible_overlap_gives_plain_generic_wording() -> None:
    hint = explain_camera_error(_raw_1023(), _fixed_ifaces(), _names(), camera_ip="192.168.8.2")
    assert hint is not None
    assert hint["kind"] == "subnet_conflict_unlocated"
    assert hint["command"] is None
    assert "overlap" in hint["message"] and "subnet mask" in hint["message"]


def test_1023_identical_subnets_have_no_narrowing_command() -> None:
    ifaces = [IfaceAddr("en13", "192.168.7.1", 24), IfaceAddr("en16", "192.168.7.108", 24)]
    hint = explain_camera_error(_raw_1023(), ifaces, _names(), camera_ip="192.168.7.2")
    assert hint is not None and hint["kind"] == "subnet_conflict"
    assert hint["command"] is None
    assert "192.168.7.0/24" in hint["message"]
    assert "AX88772A (en16" in hint["message"] and "USB 10/100/1000 LAN (en13" in hint["message"]


def test_1023_narrowing_that_would_still_overlap_has_no_command() -> None:
    # en15 is wide AND inside the camera's /24: narrowing to /24 cannot separate them
    ifaces = [IfaceAddr("en15", "192.168.8.50", 16), IfaceAddr("en13", "192.168.8.1", 24)]
    hint = explain_camera_error(_raw_1023(), ifaces, _names(), camera_ip="192.168.8.2")
    assert hint is not None and hint["command"] is None
    assert "AX88179A (en15) is 192.168.8.50/16" in hint["message"]
    narrowed = ipaddress.ip_interface("192.168.8.50/24").network
    assert narrowed.overlaps(ipaddress.ip_interface("192.168.8.1/24").network)


# -- explain_camera_error: adapter removed / missing ----------------------------------------------


def test_1024_says_the_adapter_left_the_usb_bus() -> None:
    hint = explain_camera_error(_raw_1024(), _fixed_ifaces(), _names(), camera_ip=None)
    assert hint is not None
    assert hint["kind"] == "adapter_removed"
    assert "power-cycle the Anker USB-C hub" in hint["message"]
    assert hint["command"] is None


def test_missing_camera_subnet_adapter_is_reported_as_gone() -> None:
    # en13 (the camera adapter) dropped off the bus: nothing is left on the camera's subnet
    ifaces = [i for i in _fixed_ifaces() if i.dev != "en13"]
    hint = explain_camera_error("Spinnaker: some other failure [-1010]", ifaces, _names(),
                                camera_ip="192.168.8.2")
    assert hint is not None and hint["kind"] == "adapter_missing"
    assert "192.168.8.2" in hint["message"]
    assert "power-cycle the Anker USB-C hub" in hint["message"]


def test_unrelated_errors_get_no_hint() -> None:
    assert explain_camera_error("boom", _fixed_ifaces(), _names(), camera_ip="192.168.8.2") is None
    assert explain_camera_error("boom", _fixed_ifaces(), _names(), camera_ip=None) is None
