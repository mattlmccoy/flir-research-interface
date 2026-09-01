"""Simulated camera backend for development and automated tests without an A70.

The simulator mimics the *data contract* we expect from the real camera in
temperature-linear mode: ``Mono16`` counts that are linear in Kelvin (10 mK or 100 mK per
count). Scenes are defined in degrees Celsius and encoded through the same scale the
radiometry module decodes, so the whole pipeline can be exercised end to end.

Time base: the simulator's device clock is ``frame_index / fps`` (deterministic). The host
timestamp comes from an injectable ``clock`` (defaults to :func:`time.time_ns`). With
``realtime=True`` the generator sleeps to approximate the requested frame rate.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from flir_research_interface.camera.base import (
    CameraBackend,
    DeviceDescriptor,
    Frame,
    NotConnectedError,
)
from flir_research_interface.radiometry.temperature_linear import (
    KELVIN_OFFSET,
    IRFormat,
    kelvin_per_count,
)


class Scene(Protocol):
    """A synthetic thermal scene: temperature field in degC as a function of time."""

    def render_celsius(self, t_s: float, width: int, height: int) -> npt.NDArray[np.float64]:
        """Return an (height, width) float64 array of temperatures in degC at time ``t_s``."""


@dataclass(frozen=True)
class UniformScene:
    """Every pixel at ``temperature_c``."""

    temperature_c: float

    def render_celsius(self, t_s: float, width: int, height: int) -> npt.NDArray[np.float64]:
        return np.full((height, width), self.temperature_c, dtype=np.float64)


@dataclass(frozen=True)
class GradientScene:
    """Linear ramp from ``min_c`` (left column) to ``max_c`` (right column)."""

    min_c: float
    max_c: float

    def render_celsius(self, t_s: float, width: int, height: int) -> npt.NDArray[np.float64]:
        row = np.linspace(self.min_c, self.max_c, width, dtype=np.float64)
        return np.broadcast_to(row, (height, width)).copy()


@dataclass(frozen=True)
class HotspotRampScene:
    """Circular hotspot that ramps linearly from ``start_c`` to ``end_c`` over ``ramp_s``.

    Outside the circle the field is ``background_c``. After ``ramp_s`` the hotspot holds
    at ``end_c``. This mirrors the RF-heating test case described in the project brief.
    """

    background_c: float
    start_c: float
    end_c: float
    ramp_s: float
    center_xy: tuple[int, int]
    radius_px: int

    def render_celsius(self, t_s: float, width: int, height: int) -> npt.NDArray[np.float64]:
        field = np.full((height, width), self.background_c, dtype=np.float64)
        progress = 1.0 if self.ramp_s <= 0 else min(max(t_s / self.ramp_s, 0.0), 1.0)
        hot_c = self.start_c + (self.end_c - self.start_c) * progress
        yy, xx = np.ogrid[:height, :width]
        cx, cy = self.center_xy
        mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= self.radius_px**2
        field[mask] = hot_c
        return field


def celsius_to_counts(
    celsius: npt.NDArray[np.float64], ir_format: IRFormat
) -> npt.NDArray[np.uint16]:
    """Encode degC as temperature-linear Mono16 counts (inverse of the radiometry decode)."""
    kelvin = celsius + KELVIN_OFFSET
    counts = np.rint(kelvin / kelvin_per_count(ir_format))
    return np.clip(counts, 0, np.iinfo(np.uint16).max).astype(np.uint16)


class SimulatedCameraBackend(CameraBackend):
    """Virtual A70-like camera producing deterministic temperature-linear frames."""

    MODEL = "Simulated A70"
    SERIAL = "SIM-0001"

    def __init__(
        self,
        scene: Scene,
        *,
        width: int = 640,
        height: int = 480,
        fps: float = 30.0,
        ir_format: IRFormat = IRFormat.TEMPERATURE_LINEAR_10MK,
        noise_k: float = 0.0,
        seed: int | None = None,
        clock: Callable[[], int] = time.time_ns,
        realtime: bool = False,
    ) -> None:
        if fps <= 0:
            raise ValueError("fps must be positive")
        self._scene = scene
        self._width = width
        self._height = height
        self._fps = fps
        self._ir_format = ir_format
        self._noise_k = noise_k
        self._rng = np.random.default_rng(seed)
        self._clock = clock
        self._realtime = realtime
        self._connected = False
        self._frame_index = 0

    # -- CameraBackend -----------------------------------------------------------------

    def enumerate(self) -> list[DeviceDescriptor]:
        return [
            DeviceDescriptor(
                backend="simulated",
                model=self.MODEL,
                serial=self.SERIAL,
                ip_address=None,
                mac_address=None,
                firmware="sim-0.0.1",
                interface="virtual",
            )
        ]

    def connect(self, descriptor: DeviceDescriptor) -> None:
        if descriptor.serial != self.SERIAL:
            raise NotConnectedError(f"unknown simulated device {descriptor.serial!r}")
        self._connected = True
        self._frame_index = 0

    def disconnect(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def camera_info(self) -> dict[str, Any]:
        return {
            "backend": "simulated",
            "model": self.MODEL,
            "serial": self.SERIAL,
            "width": self._width,
            "height": self._height,
            "pixel_format": "Mono16",
            "ir_format": self._ir_format.value,
            "frame_rate_hz": self._fps,
            "noise_k": self._noise_k,
            "scene": {"type": type(self._scene).__name__, **asdict(self._scene)},  # type: ignore[call-overload]
        }

    def frames(self) -> Iterator[Frame]:
        if not self._connected:
            raise NotConnectedError("simulated camera is not connected")
        period_ns = round(1e9 / self._fps)
        while self._connected:
            idx = self._frame_index
            t_s = idx / self._fps
            celsius = self._scene.render_celsius(t_s, self._width, self._height)
            if self._noise_k > 0:
                celsius = celsius + self._rng.normal(0.0, self._noise_k, celsius.shape)
            frame = Frame(
                frame_id=idx,
                device_timestamp_ns=idx * period_ns,
                host_timestamp_ns=self._clock(),
                pixel_format="Mono16",
                ir_format=self._ir_format.value,
                counts=celsius_to_counts(celsius, self._ir_format),
                incomplete=False,
            )
            self._frame_index += 1
            if self._realtime:
                time.sleep(1.0 / self._fps)
            yield frame


__all__ = [
    "GradientScene",
    "HotspotRampScene",
    "Scene",
    "SimulatedCameraBackend",
    "UniformScene",
    "celsius_to_counts",
]
