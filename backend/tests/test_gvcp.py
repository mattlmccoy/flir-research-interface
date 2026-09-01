"""Tests for SDK-independent GigE Vision (GVCP) discovery helpers.

Fixture is a real A70 DISCOVERY_ACK with the serial redacted (tests/fixtures/README.md).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from flir_research_interface.camera.gvcp import (
    GVCP_PORT,
    GvcpDevice,
    build_discovery_cmd,
    host_fix_commands,
    parse_discovery_ack,
    same_subnet,
    suggest_host_ip,
)

FIXTURE = Path(__file__).parent / "fixtures" / "discovery_ack_redacted.bin"


def _device() -> GvcpDevice:
    return parse_discovery_ack(FIXTURE.read_bytes(), source_ip="192.168.7.2")


def test_discovery_cmd_is_gvcp_discovery_with_broadcast_ack_allowed() -> None:
    cmd = build_discovery_cmd(req_id=1)
    assert GVCP_PORT == 3956
    assert cmd == bytes.fromhex("4211000200000001")


def test_parse_real_a70_ack_identity() -> None:
    dev = _device()
    assert dev.manufacturer == "FLIR Systems"
    assert dev.model == "FLIR A70"
    assert dev.device_version == "42.0.0"
    assert dev.manufacturer_info == "ACAM,Gen_A,GEV,1.0.0,GEV,1.1.0"
    assert dev.serial == "00000000"  # redacted in fixture
    assert dev.mac == "00:40:7f:11:2c:64"


def test_parse_real_a70_ack_network_config() -> None:
    dev = _device()
    assert dev.current_ip == "192.168.7.2"
    assert dev.subnet_mask == "255.255.255.0"
    assert dev.gateway == "0.0.0.0"
    assert dev.persistent_ip_enabled is True
    assert dev.dhcp_enabled is False
    assert dev.lla_enabled is True
    assert dev.source_ip == "192.168.7.2"


def test_parse_rejects_non_ack() -> None:
    with pytest.raises(ValueError, match="DISCOVERY_ACK"):
        parse_discovery_ack(bytes.fromhex("4211000200000001"), source_ip="1.2.3.4")


def test_same_subnet() -> None:
    assert same_subnet("192.168.7.1", "192.168.7.2", "255.255.255.0") is True
    assert same_subnet("169.254.168.103", "192.168.7.2", "255.255.0.0") is False


def test_suggest_host_ip_picks_dot1_unless_camera_is_dot1() -> None:
    dev = _device()
    assert suggest_host_ip(dev) == "192.168.7.1"
    dev1 = GvcpDevice(**{**dev.__dict__, "current_ip": "192.168.7.1"})
    assert suggest_host_ip(dev1) == "192.168.7.2"


def test_host_fix_commands_per_os() -> None:
    dev = _device()
    mac_cmd = host_fix_commands(
        dev, system="Darwin", interface="en13", service_name="USB 10/100/1000 LAN"
    )
    assert any(
        'networksetup -setmanual "USB 10/100/1000 LAN" 192.168.7.1 255.255.255.0' in c
        for c in mac_cmd
    )
    lin_cmd = host_fix_commands(dev, system="Linux", interface="eth1", service_name=None)
    assert any("ip addr add 192.168.7.1/24 dev eth1" in c for c in lin_cmd)
    win_cmd = host_fix_commands(dev, system="Windows", interface="Ethernet 2", service_name=None)
    assert any(
        'netsh interface ip set address "Ethernet 2" static 192.168.7.1 255.255.255.0' in c
        for c in win_cmd
    )
