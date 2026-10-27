"""Network diagnosis for camera discovery.

GigE Vision cameras (the FLIR A70) need a host interface alone on their subnet. When a second
interface shares that subnet — e.g. another lab device (a Vention printer) plugged onto the same
192.168.7.0/24 — the OS routing table becomes ambiguous and packets to the camera can egress the
wrong NIC, so the camera "randomly" fails to connect. This module turns that silent failure into an
explicit warning on the Setup page. Pure functions over the discovery payload; no I/O.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any, NamedTuple


def _network(ip: str, mask: str) -> ipaddress.IPv4Network | None:
    try:
        return ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)
    except (ValueError, TypeError):
        return None


def subnet_warnings(
    host_interfaces: list[dict[str, Any]], gvcp_devices: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """One ``subnet_conflict`` warning per camera subnet that more than one host interface shares.

    ``host_interfaces`` entries carry ``name``/``ip``/``netmask``; ``gvcp_devices`` entries carry
    ``camera_ip`` as ``"<ip>/<mask>"``. Malformed rows are skipped; an empty list means no conflict.
    """
    nets: list[tuple[Any, ipaddress.IPv4Network]] = []
    for h in host_interfaces:
        n = _network(h.get("ip", ""), h.get("netmask", ""))
        if n is not None:
            nets.append((h.get("name"), n))

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for dev in gvcp_devices:
        ip, _, mask = str(dev.get("camera_ip", "")).partition("/")
        cam_net = _network(ip, mask)
        if cam_net is None:
            continue
        on_subnet = [name for name, n in nets
                     if n.network_address == cam_net.network_address
                     and n.prefixlen == cam_net.prefixlen]
        key = str(cam_net)
        if len(on_subnet) > 1 and key not in seen:
            seen.add(key)
            others = [i for i in on_subnet if i != dev.get("via_interface")]
            eg = f" (e.g. {', '.join(others)})" if others else ""
            out.append({
                "kind": "subnet_conflict",
                "camera_subnet": key,
                "interfaces": on_subnet,
                "message": (
                    f"The {dev.get('model', 'camera')} at {ip} is on subnet {key}, which "
                    f"{len(on_subnet)} host interfaces share ({', '.join(on_subnet)}). GigE "
                    f"Vision traffic to the camera can be routed to the wrong interface, so it "
                    f"may fail to connect. Move the other device(s){eg} to a different subnet."
                ),
            })
    return out


def configured_camera_warning(
    host_interfaces: list[dict[str, Any]],
    camera_host: str | None,
    gvcp_devices: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Warn when the configured camera IP has NO host interface on its subnet, so this machine
    cannot reach it (the exact failure on a fresh Linux box whose wired adapter has no IPv4 on
    192.168.8.x).

    Returns ``None`` — no warning — when ``camera_host`` is unset/invalid, when some host interface
    is already on the camera's subnet, or when a camera was actually discovered at that IP (so it is
    plainly reachable). Otherwise a ``no_host_on_camera_subnet`` warning suggesting a host IP on the
    camera's /24.
    """
    if not camera_host:
        return None
    try:
        cam = ipaddress.ip_address(camera_host)
    except ValueError:
        return None
    for dev in gvcp_devices or []:
        found_ip, _, _ = str(dev.get("camera_ip", "")).partition("/")
        if found_ip == camera_host:
            return None  # discovered → reachable, no warning
    nets = [_network(h.get("ip", ""), h.get("netmask", "")) for h in host_interfaces]
    if any(n is not None and cam in n for n in nets):
        return None  # a NIC is already on the camera's subnet
    suggested = str(ipaddress.ip_interface(f"{camera_host}/24").network.network_address + 1)
    return {
        "kind": "no_host_on_camera_subnet",
        "camera_host": camera_host,
        "message": (
            f"The camera is configured at {camera_host}, but no network interface on this machine "
            f"is on that subnet — so it cannot be reached and will not appear in discovery. Give "
            f"the wired adapter a static IP on the camera's subnet (e.g. {suggested}) and, on "
            f"Linux, allow GigE Vision through the firewall. See docs/camera_setup.md."
        ),
    }


# -- connect failures (Spinnaker -1023 / -1024) -------------------------------------------------

#: Shown when the camera's adapter is gone. The Anker hub is the one piece of lab hardware named
#: here: both GigE adapters ride it, and a hub power-cycle is what brings them back.
_HUB_HINT = (
    "power-cycle the Anker USB-C hub (and check the RF coax ground if it keeps happening)."
)
_PORT_LINE = re.compile(r"^Hardware Port:\s*(.+?)\s*$")
_DEVICE_LINE = re.compile(r"^Device:\s*(\S+)\s*$")


class IfaceAddr(NamedTuple):
    """One IPv4 address on a host adapter: BSD device, address, prefix length."""

    dev: str
    ip: str
    prefix: int


def parse_hardware_ports(text: str) -> dict[str, str]:
    """Map BSD device -> hardware port name from ``networksetup -listallhardwareports``.

    Each block is ``Hardware Port: <name>`` then ``Device: <dev>``; anything else is ignored.
    """
    names: dict[str, str] = {}
    port: str | None = None
    for line in text.splitlines():
        p = _PORT_LINE.match(line.strip())
        if p:
            port = p.group(1)
            continue
        d = _DEVICE_LINE.match(line.strip())
        if d and port:
            names[d.group(1)] = port
            port = None
    return names


def _iface_net(a: IfaceAddr) -> ipaddress.IPv4Network | None:
    try:
        return ipaddress.IPv4Network(f"{a.ip}/{a.prefix}", strict=False)
    except (ValueError, TypeError):
        return None


def overlapping_subnets(ifaces: list[IfaceAddr]) -> list[tuple[IfaceAddr, IfaceAddr]]:
    """Pairs of addresses on DIFFERENT devices whose networks overlap, each as (wider, narrower).

    Pairs come in input order; with equal prefixes the earlier address is first. Malformed rows
    are skipped.
    """
    rows = [(a, n) for a in ifaces if (n := _iface_net(a)) is not None]
    out: list[tuple[IfaceAddr, IfaceAddr]] = []
    for i, (a, na) in enumerate(rows):
        for b, nb in rows[i + 1:]:
            if a.dev == b.dev or not na.overlaps(nb):
                continue
            out.append((b, a) if b.prefix < a.prefix else (a, b))
    return out


def _label(a: IfaceAddr, names: dict[str, str]) -> str:
    """'AX88179A (en15)' or just 'en15' when the port name is unknown."""
    name = names.get(a.dev)
    return f"{name} ({a.dev})" if name else a.dev


def _label_addr(a: IfaceAddr, names: dict[str, str]) -> str:
    """'USB 10/100/1000 LAN (en13, 192.168.8.1/24)' or 'en13 (192.168.8.1/24)'."""
    name = names.get(a.dev)
    addr = f"{a.ip}/{a.prefix}"
    return f"{name} ({a.dev}, {addr})" if name else f"{a.dev} ({addr})"


def _contains(a: IfaceAddr, ip: str | None) -> bool:
    net = _iface_net(a)
    if net is None or not ip:
        return False
    try:
        return ipaddress.IPv4Address(ip) in net
    except ValueError:
        return False


def _hint(kind: str, message: str, command: str | None = None) -> dict[str, Any]:
    return {"kind": kind, "message": message, "command": command}


def _explain_overlap(
    ifaces: list[IfaceAddr], names: dict[str, str], camera_ip: str | None
) -> dict[str, Any]:
    pairs = overlapping_subnets(ifaces)
    if camera_ip:  # when we know where the camera is, only overlaps with ITS adapter matter
        on_cam = [p for p in pairs if _contains(p[0], camera_ip) or _contains(p[1], camera_ip)]
        pairs = on_cam or pairs
    if not pairs:
        return _hint(
            "subnet_conflict_unlocated",
            "Camera can't connect: Spinnaker reports that another network adapter's address range "
            "overlaps the camera adapter's, but no overlap shows among this Mac's adapters now. "
            "Check each adapter's subnet mask in System Settings > Network (the camera adapter "
            "should be the only one on its subnet).",
        )
    wide = min((p[0] for p in pairs), key=lambda a: a.prefix)
    others = [p[1] if p[0] == wide else p[0] for p in pairs if wide in p]
    cam_adapter = next((o for o in others if _contains(o, camera_ip)), None)
    if cam_adapter is not None:
        others = [cam_adapter]
    if all(o.prefix == wide.prefix for o in others):
        both = [wide, *others]
        net = _iface_net(wide)
        return _hint(
            "subnet_conflict",
            f"Camera can't connect: adapters {' and '.join(_label_addr(a, names) for a in both)} "
            f"are on the same subnet {net}. Move the adapter the camera is not plugged into to a "
            f"different subnet.",
        )
    target = max(o.prefix for o in others)
    narrowed = ipaddress.IPv4Network(f"{wide.ip}/{target}", strict=False)
    still = any(narrowed.overlaps(n) for o in others if (n := _iface_net(o)) is not None)
    what = (f"the camera adapter {_label_addr(cam_adapter, names)}" if cam_adapter is not None
            else " and ".join(_label_addr(o, names) for o in others))
    head = f"Camera can't connect: adapter {_label(wide, names)} is {wide.ip}/{wide.prefix}, " \
           f"which overlaps {what}."
    if still:
        return _hint("subnet_conflict",
                     f"{head} Give it an address on a subnet of its own (not {narrowed}).")
    service = names.get(wide.dev, wide.dev)
    return _hint(
        "subnet_conflict",
        f"{head} Narrow it to /{target} in Terminal:",
        f'sudo networksetup -setmanual "{service}" {wide.ip} {narrowed.netmask}',
    )


def explain_camera_error(
    raw: str, ifaces: list[IfaceAddr], names: dict[str, str], camera_ip: str | None
) -> dict[str, Any] | None:
    """Plain-language cause of a camera connect/stream failure, or ``None`` when there is nothing
    better to say than the raw error.

    ``raw`` is the error text, ``ifaces`` this machine's IPv4 addresses, ``names`` device -> macOS
    port/service name, ``camera_ip`` the camera's address when known. Returns
    ``{"kind", "message", "command"}``; ``command`` is a copy-paste fix or ``None``.
    """
    if "[-1023]" in raw:
        return _explain_overlap(ifaces, names, camera_ip)
    if "[-1024]" in raw:
        return _hint("adapter_removed",
                     "The camera's network adapter disappeared from the USB bus — " + _HUB_HINT)
    if camera_ip and ifaces and not any(_contains(a, camera_ip) for a in ifaces):
        return _hint(
            "adapter_missing",
            f"No network adapter on this Mac is on the camera's subnet ({camera_ip}), so the "
            f"camera's adapter has likely disappeared from the USB bus — " + _HUB_HINT,
        )
    return None


__all__ = [
    "IfaceAddr",
    "configured_camera_warning",
    "explain_camera_error",
    "overlapping_subnets",
    "parse_hardware_ports",
    "subnet_warnings",
]
