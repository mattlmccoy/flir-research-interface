"""camera_error_hint: the I/O wrapper that gathers adapters + names on failure and never raises.

The adapter snapshot is injected; these tests never call psutil or networksetup.
"""

from __future__ import annotations

import pytest

from flir_research_interface import connect_hint
from flir_research_interface.connect_hint import camera_error_hint
from flir_research_interface.net_diagnostics import IfaceAddr

RAW_1023 = ("Spinnaker: Spinnaker: Camera is on an adapter with conflicting IP and subnet "
            "address range. [-1023]")  # tests/fixtures/neterr/spinnaker_1023_log.txt
RAW_1024 = ("Spinnaker: Camera has been removed from the list and is no longer valid. [-1024]")
CONFLICT = ([IfaceAddr("en15", "192.168.9.1", 16), IfaceAddr("en13", "192.168.8.1", 24)],
            {"en15": "AX88179A", "en13": "USB 10/100/1000 LAN"})


def test_1023_uses_the_snapshot() -> None:
    hint = camera_error_hint(RAW_1023, "192.168.8.2", snapshot=lambda: CONFLICT)
    assert hint is not None
    assert hint["command"] == 'sudo networksetup -setmanual "AX88179A" 192.168.9.1 255.255.255.0'


def test_a_failing_snapshot_still_gives_plain_generic_wording() -> None:
    def broken() -> tuple[list[IfaceAddr], dict[str, str]]:
        raise OSError("psutil unavailable")

    hint = camera_error_hint(RAW_1023, "192.168.8.2", snapshot=broken)
    assert hint is not None and hint["kind"] == "subnet_conflict_unlocated"


def test_1024_needs_no_snapshot() -> None:
    def never() -> tuple[list[IfaceAddr], dict[str, str]]:
        raise AssertionError("must not look at adapters for -1024")

    hint = camera_error_hint(RAW_1024, None, snapshot=never)
    assert hint is not None and hint["kind"] == "adapter_removed"


def test_unrelated_error_without_camera_ip_does_no_io() -> None:
    def never() -> tuple[list[IfaceAddr], dict[str, str]]:
        raise AssertionError("no diagnosis possible, so no I/O")

    assert camera_error_hint("boom", None, snapshot=never) is None


def test_never_raises_even_if_the_explainer_breaks(monkeypatch: pytest.MonkeyPatch) -> None:
    def bad(*_a: object, **_k: object) -> None:
        raise RuntimeError("bug")

    monkeypatch.setattr(connect_hint, "explain_camera_error", bad)
    assert camera_error_hint(RAW_1023, None, snapshot=lambda: CONFLICT) is None


def test_netmask_to_prefix_snapshot_conversion() -> None:
    assert connect_hint.prefix_of("255.255.0.0") == 16
    assert connect_hint.prefix_of("255.255.255.0") == 24
