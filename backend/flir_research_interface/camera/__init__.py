"""Camera backends: registry and factory.

Only this subpackage may touch vendor SDKs (PySpin). Register a backend with
:func:`register_backend` and build one with :func:`create_backend`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from flir_research_interface.camera.base import (
    CameraBackend,
    CameraError,
    DeviceDescriptor,
    Frame,
    NotConnectedError,
)

CAMERA_BACKENDS: dict[str, type[CameraBackend]] = {}


def register_backend(name: str) -> Callable[[type[CameraBackend]], type[CameraBackend]]:
    """Class decorator registering a backend under ``name``."""

    def decorator(cls: type[CameraBackend]) -> type[CameraBackend]:
        CAMERA_BACKENDS[name] = cls
        return cls

    return decorator


def create_backend(name: str, **kwargs: Any) -> CameraBackend:
    """Instantiate the backend registered as ``name``. Raises ``KeyError`` if unknown."""
    try:
        cls = CAMERA_BACKENDS[name]
    except KeyError:
        known = sorted(CAMERA_BACKENDS)
        raise KeyError(f"unknown camera backend {name!r}; known: {known}") from None
    return cls(**kwargs)


# Register built-in backends. Import here (not at the top) so base types are defined first.
from flir_research_interface.camera.simulated import SimulatedCameraBackend  # noqa: E402

register_backend("simulated")(SimulatedCameraBackend)

__all__ = [
    "CAMERA_BACKENDS",
    "CameraBackend",
    "CameraError",
    "DeviceDescriptor",
    "Frame",
    "NotConnectedError",
    "SimulatedCameraBackend",
    "create_backend",
    "register_backend",
]
