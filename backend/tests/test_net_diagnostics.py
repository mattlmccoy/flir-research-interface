"""Discovery-time network diagnosis: warn when another host interface shares the camera's subnet.

Fixtures are captured from the real GET /api/setup/discovery payload on the day a Vention printer
was plugged onto the camera's subnet (en13 + en16 both on 192.168.7.0/24), which routed GigE Vision
traffic to the wrong interface.
"""

from __future__ import annotations

from flir_research_interface.net_diagnostics import subnet_warnings

# Real capture: two host interfaces on 192.168.7.0/24 (the camera NIC + the Vention link) + en0.
CONFLICT_IFACES = [
    {"name": "en0", "ip": "10.90.78.96", "netmask": "255.255.128.0"},
    {"name": "en13", "ip": "192.168.7.1", "netmask": "255.255.255.0"},
    {"name": "en16", "ip": "192.168.7.108", "netmask": "255.255.255.0"},
]
CAMERA = [{"model": "FLIR A70", "serial": "89903739", "via_interface": "en13",
           "camera_ip": "192.168.7.2/255.255.255.0"}]


def test_warns_when_two_host_interfaces_share_the_camera_subnet() -> None:
    w = subnet_warnings(CONFLICT_IFACES, CAMERA)
    assert len(w) == 1
    warn = w[0]
    assert warn["kind"] == "subnet_conflict"
    assert warn["camera_subnet"] == "192.168.7.0/24"
    assert set(warn["interfaces"]) == {"en13", "en16"}
    # message names both interfaces and the camera so the operator can act
    assert "en16" in warn["message"] and "en13" in warn["message"]
    assert "192.168.7" in warn["message"]


def test_no_warning_when_camera_has_its_subnet_to_itself() -> None:
    # Only the camera NIC on 192.168.7.x; en0 is unrelated → clean, no warning.
    ifaces = [
        {"name": "en0", "ip": "10.90.78.96", "netmask": "255.255.128.0"},
        {"name": "en13", "ip": "192.168.7.1", "netmask": "255.255.255.0"},
    ]
    assert subnet_warnings(ifaces, CAMERA) == []


def test_no_camera_no_warning_and_bad_shapes_are_ignored() -> None:
    assert subnet_warnings(CONFLICT_IFACES, []) == []
    # malformed ip/mask must not crash
    assert subnet_warnings([{"name": "x", "ip": "nope", "netmask": ""}], CAMERA) == []
