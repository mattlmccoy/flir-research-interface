"""Plain-language hint for a failed camera connect: gathers this machine's adapters only when a
connect or stream has failed (never per frame) and never raises.

The reasoning lives in :func:`net_diagnostics.explain_camera_error` (pure, tested on real
captures); this module only does the I/O: psutil for IPv4 addresses, ``networksetup`` for macOS
names. Any I/O failure degrades to an empty snapshot, which still yields plain generic wording; an
unexpected bug yields ``None`` so the caller shows the raw error alone.
"""

from __future__ import annotations

import ipaddress
import logging
import platform
import subprocess
from collections.abc import Callable
from typing import Any

from flir_research_interface.net_diagnostics import (
    IfaceAddr,
    explain_camera_error,
    parse_hardware_ports,
)

logger = logging.getLogger(__name__)

Snapshot = Callable[[], tuple[list[IfaceAddr], dict[str, str]]]

#: Absolute path: /usr/sbin is not on the launchd PATH the operator runs under (see camera/gvcp.py).
_NETWORKSETUP = "/usr/sbin/networksetup"


def prefix_of(netmask: str) -> int:
    """Prefix length of a dotted netmask ('255.255.0.0' -> 16)."""
    return ipaddress.IPv4Network(f"0.0.0.0/{netmask}").prefixlen


def _hardware_port_names() -> dict[str, str]:
    try:
        out = subprocess.run([_NETWORKSETUP, "-listallhardwareports"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    return parse_hardware_ports(out)


def _live_snapshot() -> tuple[list[IfaceAddr], dict[str, str]]:
    """This machine's IPv4 addresses and device -> name map.

    Names prefer the network SERVICE name (what ``networksetup -setmanual`` takes; it differs
    from the hardware-port name when macOS has duplicated a service), falling back to the
    hardware-port name.
    """
    from flir_research_interface.camera import gvcp

    hosts = gvcp.host_interfaces()
    names = _hardware_port_names() if platform.system() == "Darwin" else {}
    names.update({h.name: h.service_name for h in hosts if h.service_name})
    return [IfaceAddr(h.name, h.ip, prefix_of(h.netmask)) for h in hosts], names


def camera_error_hint(
    raw: str, camera_ip: str | None, *, snapshot: Snapshot | None = None
) -> dict[str, Any] | None:
    """``{"kind", "message", "command"}`` explaining ``raw`` in plain words, or ``None``.

    ``snapshot`` defaults to this machine's live adapters, looked up at call time.
    """
    try:
        needs_adapters = "[-1023]" in raw or ("[-1024]" not in raw and bool(camera_ip))
        ifaces: list[IfaceAddr] = []
        names: dict[str, str] = {}
        if needs_adapters:
            try:
                ifaces, names = (snapshot or _live_snapshot)()
            except Exception:  # noqa: BLE001 - psutil/networksetup trouble -> generic wording
                logger.warning("could not list network adapters for the connect hint",
                               exc_info=True)
        return explain_camera_error(raw, ifaces, names, camera_ip)
    except Exception:  # noqa: BLE001 - a diagnosis must never break connect handling
        logger.exception("connect hint failed; showing the raw error only")
        return None


__all__ = ["camera_error_hint", "prefix_of"]
