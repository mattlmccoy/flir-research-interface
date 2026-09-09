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


__all__ = ["subnet_warnings"]
