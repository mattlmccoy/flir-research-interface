"""Shared pytest configuration.

Hardware tests (marked ``hardware``) are deselected unless ``--hardware`` is passed.
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--hardware",
        action="store_true",
        default=False,
        help="run tests that need a physical FLIR camera and PySpin",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--hardware"):
        return
    skip = pytest.mark.skip(reason="needs --hardware and a connected camera")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip)
