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
from flir_research_interface.camera.controls import COMMANDS, validate_values
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
    # The three factory cases the real A70 reported (°C), used only to mimic its info shape.
    CASES_C: tuple[tuple[float, float], ...] = ((-20.0, 175.0), (-20.0, 250.0), (175.0, 1000.0))
    ENUM_OPTIONS: dict[str, list[str]] = {
        "NUCMode": ["Off", "Automatic"],
        "IRFrameRate": ["Rate60Hz", "Rate30Hz", "Rate15Hz", "Rate7Hz", "Rate4Hz"],
    }
    RATE_HZ: dict[str, float] = {
        "Rate60Hz": 60.0, "Rate30Hz": 30.0, "Rate15Hz": 15.0, "Rate7Hz": 7.5, "Rate4Hz": 3.75
    }

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
        self._params: dict[str, float] = {
            "ObjectEmissivity": 0.95,
            "ReflectedTemperature": 293.15,
            "AtmosphericTemperature": 293.15,
            "ObjectDistance": 1.0,
            "RelativeHumidity": 0.5,
            "ExtOpticsTemperature": 293.15,
            "ExtOpticsTransmission": 1.0,
        }
        self._case = 1
        self._nuc_mode = "Automatic"
        self._ir_frame_rate = min(self.RATE_HZ, key=lambda k: abs(self.RATE_HZ[k] - fps))
        self._nuc_count = 0

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
        cases = [
            {
                "index": i,
                "low_k": lo + KELVIN_OFFSET,
                "high_k": hi + KELVIN_OFFSET,
                "enabled": True,
                "low_c": lo,
                "high_c": hi,
            }
            for i, (lo, hi) in enumerate(self.CASES_C)
        ]
        return {
            "backend": "simulated",
            "model": self.MODEL,
            "serial": self.SERIAL,
            "width": self._width,
            "height": self._height,
            "pixel_format": "Mono16",
            "ir_format": self._ir_format.value,
            "frame_rate_hz": self._fps,
            "ir_frame_rate": self._ir_frame_rate,
            "noise_k": self._noise_k,
            "scene": {"type": type(self._scene).__name__, **asdict(self._scene)},  # type: ignore[call-overload]
            "measurement_cases": cases,
            "active_case": cases[self._case],
            "object_parameters": dict(self._params),
            "nuc_mode": self._nuc_mode,
            "device_temperature_c": 34.0,
            "nuc_count": self._nuc_count,
            "enum_options": {k: list(v) for k, v in self.ENUM_OPTIONS.items()},
        }

    def set_parameters(self, values: dict[str, Any]) -> dict[str, Any]:
        clean = validate_values(
            values, enum_options=self.ENUM_OPTIONS, n_cases=len(self.CASES_C)
        )
        for name, v in clean.items():
            if name == "CurrentCase":
                self._case = int(v)
            elif name == "NUCMode":
                self._nuc_mode = str(v)
            elif name == "IRFrameRate":
                self._ir_frame_rate = str(v)
                self._fps = self.RATE_HZ[str(v)]
            else:
                self._params[name] = float(v)
        return clean

    def execute(self, command: str) -> None:
        if command not in COMMANDS:
            raise ValueError(f"unknown command {command!r}")
        self._nuc_count += 1

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
