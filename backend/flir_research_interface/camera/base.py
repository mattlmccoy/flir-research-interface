"""Hardware abstraction layer for thermal cameras.

Nothing outside ``flir_research_interface.camera`` may import PySpin. Backends implement
:class:`CameraBackend`; the rest of the application only sees :class:`Frame`,
:class:`DeviceDescriptor` and plain dictionaries.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt


class CameraError(RuntimeError):
    """Base class for camera backend errors."""


class NotConnectedError(CameraError):
    """Raised when an operation needs a connected camera."""


@dataclass(frozen=True)
class DeviceDescriptor:
    """Identity of a discovered camera, before connection."""

    backend: str
    model: str
    serial: str
    ip_address: str | None
    mac_address: str | None
    firmware: str | None
    interface: str


@dataclass(frozen=True)
class Frame:
    """One acquired image, as delivered by the camera (no visualisation applied).

    ``counts`` holds the raw 16-bit values exactly as received. Converting them to
    temperature is the job of :mod:`flir_research_interface.radiometry` and depends on
    ``ir_format``. ``device_timestamp_ns`` is the camera/transport timestamp reported by
    the SDK; ``host_timestamp_ns`` is ``time.time_ns()`` on the acquisition host at receipt.
    """

    frame_id: int
    device_timestamp_ns: int
    host_timestamp_ns: int
    pixel_format: str
    ir_format: str
    counts: npt.NDArray[np.uint16]
    incomplete: bool

    def __post_init__(self) -> None:
        if self.counts.dtype != np.uint16:
            raise TypeError(f"Frame.counts must be uint16, got {self.counts.dtype}")
        if self.counts.ndim != 2:
            raise ValueError(
                f"Frame.counts must be 2-D (height, width), got ndim={self.counts.ndim}"
            )

    @property
    def height(self) -> int:
        return int(self.counts.shape[0])

    @property
    def width(self) -> int:
        return int(self.counts.shape[1])


class CameraBackend(ABC):
    """Abstract camera. One instance manages one connection lifecycle."""

    @abstractmethod
    def enumerate(self) -> list[DeviceDescriptor]:
        """Discover cameras visible to this backend (does not connect)."""

    @abstractmethod
    def connect(self, descriptor: DeviceDescriptor) -> None:
        """Open the camera described by ``descriptor``."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close the camera and release SDK resources. Idempotent."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """True while a camera is open."""

    @abstractmethod
    def camera_info(self) -> dict[str, Any]:
        """Return an auditable snapshot of camera identity and settings."""

    @abstractmethod
    def frames(self) -> Iterator[Frame]:
        """Yield frames continuously until the consumer stops iterating or disconnects."""

    # -- controls (optional; brief §30) --------------------------------------------------

    def set_parameters(self, values: dict[str, Any]) -> dict[str, Any]:
        """Write camera nodes (object parameters, CurrentCase, NUCMode, IRFrameRate).

        Returns the values read back. Raises ``ValueError`` for an unknown node or an
        out-of-range value and ``CameraError`` when the backend cannot write.
        """
        raise CameraError(f"{type(self).__name__} does not support writing camera parameters")

    def execute(self, command: str) -> None:
        """Run a command node such as ``NUCAction``. ``ValueError`` for an unknown command."""
        raise CameraError(f"{type(self).__name__} does not support command {command!r}")

    def __enter__(self) -> CameraBackend:
        return self

    def __exit__(self, *exc: object) -> None:
        self.disconnect()


__all__ = [
    "CameraBackend",
    "CameraError",
    "DeviceDescriptor",
    "Frame",
    "NotConnectedError",
]
