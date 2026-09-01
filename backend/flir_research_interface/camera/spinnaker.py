"""Spinnaker/PySpin camera backend (placeholder, gated on Milestone-1 probe output).

Status: NOT IMPLEMENTED on purpose. The application must not assume radiometric GenICam
node names from other FLIR models. Once ``fri-probe`` has been run against the physical A70
and its ``probe_report.json`` reviewed, this module will implement :class:`CameraBackend`
using only nodes that were observed on that camera. Until then the only PySpin code in the
project is the read-only probe in :mod:`flir_research_interface.probe`.
"""

from __future__ import annotations

from flir_research_interface.camera.base import CameraBackend


class SpinnakerCameraBackend(CameraBackend):  # pragma: no cover - placeholder
    """Will wrap PySpin. Instantiating it today raises to make the gap explicit."""

    def __init__(self) -> None:
        raise NotImplementedError(
            "SpinnakerCameraBackend is gated on the Milestone-1 probe output. "
            "Run `fri-probe` against the camera first (docs/installation.md)."
        )

    def enumerate(self):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def connect(self, descriptor):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def disconnect(self) -> None:
        raise NotImplementedError

    @property
    def is_connected(self) -> bool:
        return False

    def camera_info(self):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def frames(self):  # type: ignore[no-untyped-def]
        raise NotImplementedError


__all__ = ["SpinnakerCameraBackend"]
