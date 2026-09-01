"""SDK-independent GigE Vision discovery (GVCP) and subnet diagnosis.

Why this exists: GenICam stacks (Spinnaker included) only list cameras whose IP lies inside a
host adapter's subnet. A camera on the wrong subnet still answers a GVCP DISCOVERY_CMD
broadcast, so this module can *find* it and tell the user how to fix the host adapter. It is
read-only: it never changes camera or host settings.

Packet layout follows the GigE Vision specification (GVCP DISCOVERY_ACK payload offsets) and
was checked against a real FLIR A70 reply captured on 2026-09-01 (tests/fixtures/).
"""

from __future__ import annotations

import ipaddress
import platform
import socket
import struct
import subprocess
import time
from dataclasses import dataclass

GVCP_PORT = 3956
_GVCP_KEY = 0x42
_FLAG_ACK_REQUIRED = 0x01
_FLAG_ALLOW_BROADCAST_ACK = 0x10
_CMD_DISCOVERY = 0x0002
_ACK_DISCOVERY = 0x0003


@dataclass(frozen=True)
class GvcpDevice:
    """One camera's DISCOVERY_ACK, decoded."""

    source_ip: str
    mac: str
    current_ip: str
    subnet_mask: str
    gateway: str
    ip_config_options: int
    ip_config_current: int
    manufacturer: str
    model: str
    device_version: str
    manufacturer_info: str
    serial: str
    user_name: str

    @property
    def persistent_ip_enabled(self) -> bool:
        return bool(self.ip_config_current & 0x1)

    @property
    def dhcp_enabled(self) -> bool:
        return bool(self.ip_config_current & 0x2)

    @property
    def lla_enabled(self) -> bool:
        return bool(self.ip_config_current & 0x4)


def build_discovery_cmd(req_id: int = 1) -> bytes:
    """GVCP DISCOVERY_CMD asking for an ack and allowing broadcast acks."""
    flags = _FLAG_ACK_REQUIRED | _FLAG_ALLOW_BROADCAST_ACK
    return struct.pack(">BBHHH", _GVCP_KEY, flags, _CMD_DISCOVERY, 0, req_id & 0xFFFF)


def _cstr(buf: bytes, off: int, ln: int) -> str:
    return buf[off : off + ln].split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def _ip(buf: bytes, off: int) -> str:
    return ".".join(str(b) for b in buf[off : off + 4])


def parse_discovery_ack(data: bytes, *, source_ip: str) -> GvcpDevice:
    """Decode a DISCOVERY_ACK datagram. Raises ValueError for anything else."""
    if len(data) < 8 + 248:
        raise ValueError("not a GVCP DISCOVERY_ACK: too short")
    status, ack, _length, _req = struct.unpack(">HHHH", data[:8])
    if ack != _ACK_DISCOVERY or status != 0:
        raise ValueError(f"not a GVCP DISCOVERY_ACK (ack=0x{ack:04x}, status=0x{status:04x})")
    p = data[8:]
    return GvcpDevice(
        source_ip=source_ip,
        mac=":".join(f"{b:02x}" for b in p[10:16]),
        current_ip=_ip(p, 36),
        subnet_mask=_ip(p, 52),
        gateway=_ip(p, 68),
        ip_config_options=struct.unpack(">I", p[16:20])[0],
        ip_config_current=struct.unpack(">I", p[20:24])[0],
        manufacturer=_cstr(p, 72, 32),
        model=_cstr(p, 104, 32),
        device_version=_cstr(p, 136, 32),
        manufacturer_info=_cstr(p, 168, 48),
        serial=_cstr(p, 216, 16),
        user_name=_cstr(p, 232, 16),
    )


def same_subnet(ip_a: str, ip_b: str, mask: str) -> bool:
    net = ipaddress.IPv4Network(f"{ip_a}/{mask}", strict=False)
    return ipaddress.IPv4Address(ip_b) in net


def suggest_host_ip(device: GvcpDevice) -> str:
    """A free-looking host address inside the camera's subnet (.1, or .2 if the camera is .1)."""
    net = ipaddress.IPv4Network(f"{device.current_ip}/{device.subnet_mask}", strict=False)
    cam = ipaddress.IPv4Address(device.current_ip)
    first = net.network_address + 1
    candidate = first if first != cam else first + 1
    return str(candidate)


def host_fix_commands(
    device: GvcpDevice, *, system: str, interface: str, service_name: str | None
) -> tuple[str, ...]:
    """Copy-paste commands that move the host adapter onto the camera's subnet."""
    host_ip = suggest_host_ip(device)
    prefix = ipaddress.IPv4Network(f"0.0.0.0/{device.subnet_mask}").prefixlen
    if system == "Darwin":
        svc = service_name or interface
        return (
            f'sudo networksetup -setmanual "{svc}" {host_ip} {device.subnet_mask}',
            f'# revert later: sudo networksetup -setdhcp "{svc}"',
        )
    if system == "Linux":
        return (
            f"sudo ip addr add {host_ip}/{prefix} dev {interface}",
            f"# revert later: sudo ip addr del {host_ip}/{prefix} dev {interface}",
        )
    if system == "Windows":
        return (
            f'netsh interface ip set address "{interface}" static {host_ip} {device.subnet_mask}',
            f'# revert later: netsh interface ip set address "{interface}" dhcp',
        )
    return (f"set the adapter {interface} to {host_ip}/{prefix}",)


@dataclass(frozen=True)
class HostInterface:
    name: str
    ip: str
    netmask: str
    broadcast: str
    service_name: str | None


def _macos_service_names() -> dict[str, str]:
    try:
        out = subprocess.run(
            ["networksetup", "-listallhardwareports"], capture_output=True, text=True, timeout=5
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    names: dict[str, str] = {}
    port = None
    for line in out.splitlines():
        if line.startswith("Hardware Port:"):
            port = line.split(":", 1)[1].strip()
        elif line.startswith("Device:") and port:
            names[line.split(":", 1)[1].strip()] = port
    return names


def host_interfaces() -> list[HostInterface]:
    """IPv4 interfaces (excluding loopback) via psutil, with macOS service names when available."""
    import psutil

    svc = _macos_service_names() if platform.system() == "Darwin" else {}
    result: list[HostInterface] = []
    for name, addrs in psutil.net_if_addrs().items():
        for a in addrs:
            if a.family != socket.AF_INET or a.address.startswith("127."):
                continue
            mask = a.netmask or "255.255.255.255"
            bcast = a.broadcast or str(
                ipaddress.IPv4Network(f"{a.address}/{mask}", strict=False).broadcast_address
            )
            result.append(HostInterface(name, a.address, mask, bcast, svc.get(name)))
    return result


@dataclass(frozen=True)
class DiscoveryHit:
    interface: HostInterface
    device: GvcpDevice

    @property
    def reachable_by_sdk(self) -> bool:
        """True when the camera is inside this adapter's subnet (GenICam stacks require it)."""
        return same_subnet(self.interface.ip, self.device.current_ip, self.interface.netmask)


def discover(timeout_s: float = 1.5) -> list[DiscoveryHit]:
    """Broadcast DISCOVERY_CMD from every IPv4 interface and collect replies."""
    hits: list[DiscoveryHit] = []
    for iface in host_interfaces():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(timeout_s)
        try:
            sock.bind((iface.ip, 0))
            for dst in {iface.broadcast, "255.255.255.255"}:
                try:
                    sock.sendto(build_discovery_cmd(), (dst, GVCP_PORT))
                except OSError:
                    continue
            deadline = time.monotonic() + timeout_s
            seen: set[str] = set()
            while time.monotonic() < deadline:
                try:
                    data, addr = sock.recvfrom(4096)
                except TimeoutError:
                    break
                try:
                    dev = parse_discovery_ack(data, source_ip=addr[0])
                except ValueError:
                    continue
                if dev.mac in seen:
                    continue
                seen.add(dev.mac)
                hits.append(DiscoveryHit(iface, dev))
        except OSError:
            continue
        finally:
            sock.close()
    return hits


__all__ = [
    "GVCP_PORT",
    "DiscoveryHit",
    "GvcpDevice",
    "HostInterface",
    "build_discovery_cmd",
    "discover",
    "host_fix_commands",
    "host_interfaces",
    "parse_discovery_ack",
    "same_subnet",
    "suggest_host_ip",
]
