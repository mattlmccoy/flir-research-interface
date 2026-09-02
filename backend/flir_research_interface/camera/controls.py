"""Writable camera controls shared by the Spinnaker and simulated backends (brief §30).

Everything here is validation only; no node is invented. Names, units and ranges are the
ones the A70 probe reported (docs/radiometry.md): object temperatures in Kelvin, humidity and
transmission as fractions, ``CurrentCase`` an index into the camera's factory cases,
``NUCMode`` and ``IRFrameRate`` enumerations whose entries come from the camera itself.
"""

from __future__ import annotations

from typing import Any

FLOAT_NODES: dict[str, tuple[float, float]] = {
    "ObjectEmissivity": (0.0, 1.0),
    "ReflectedTemperature": (0.0, 5000.0),
    "AtmosphericTemperature": (0.0, 5000.0),
    "ObjectDistance": (0.0, 10000.0),
    "RelativeHumidity": (0.0, 1.0),
    "ExtOpticsTemperature": (0.0, 5000.0),
    "ExtOpticsTransmission": (0.0, 1.0),
}
"""Float nodes with the min/max the camera reports."""

ENUM_NODES: tuple[str, ...] = ("NUCMode", "IRFrameRate")
INT_NODES: tuple[str, ...] = ("CurrentCase",)
COMMANDS: tuple[str, ...] = ("NUCAction",)
WRITABLE_NODES: tuple[str, ...] = tuple(FLOAT_NODES) + INT_NODES + ENUM_NODES


def _as_float(name: str, v: Any) -> float:
    if isinstance(v, bool) or not isinstance(v, int | float):
        raise ValueError(f"{name} must be a number")
    return float(v)


def validate_values(
    values: dict[str, Any], *, enum_options: dict[str, list[str]], n_cases: int
) -> dict[str, Any]:
    """Return a normalised copy of ``values`` or raise ``ValueError`` (nothing is written)."""
    out: dict[str, Any] = {}
    for name, v in values.items():
        if name in FLOAT_NODES:
            lo, hi = FLOAT_NODES[name]
            f = _as_float(name, v)
            if not lo <= f <= hi:
                raise ValueError(f"{name} must be within {lo}…{hi}, got {f}")
            out[name] = f
        elif name in INT_NODES:
            if isinstance(v, bool) or not isinstance(v, int | float) or not float(v).is_integer():
                raise ValueError(f"{name} must be an integer")
            i = int(v)
            if not 0 <= i < n_cases:
                raise ValueError(f"{name} must be within 0…{n_cases - 1}, got {i}")
            out[name] = i
        elif name in ENUM_NODES:
            options = enum_options.get(name, [])
            if not isinstance(v, str) or v not in options:
                raise ValueError(f"{name} must be one of {options}, got {v!r}")
            out[name] = v
        else:
            raise ValueError(f"{name} is not a writable camera parameter")
    return out


__all__ = [
    "COMMANDS",
    "ENUM_NODES",
    "FLOAT_NODES",
    "INT_NODES",
    "WRITABLE_NODES",
    "validate_values",
]
