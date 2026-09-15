"""Network diagnosis for camera discovery.

GigE Vision cameras (the FLIR A70) need a host interface alone on their subnet. When a second
interface shares that subnet — e.g. another lab device (a Vention printer) plugged onto the same
192.168.7.0/24 — the OS routing table becomes ambiguous and packets to the camera can egress the
wrong NIC, so the camera "randomly" fails to connect. This module turns that silent failure into an
explicit warning on the Setup page. Pure functions over the discovery payload; no I/O.
"""

from __future__ import annotations

import ipaddress
from typing import Any


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
    nets = [(h.get("name"), _network(h.get("ip", ""), h.get("netmask", "")))
            for h in host_interfaces]
    nets = [(name, n) for name, n in nets if n is not None]

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


__all__ = ["configured_camera_warning", "subnet_warnings"]
