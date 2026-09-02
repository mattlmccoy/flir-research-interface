"""Per-ROI emissivity: re-correct the camera's temperature-linear output for a different
emissivity / reflected temperature using the camera's own R, B, F constants (metadata
camera.calibration_constants; A70 FOL08 2026-09-02: R=22474.88, B=1520, F=1.05)."""

from __future__ import annotations

import numpy as np
import pytest

from flir_research_interface.radiometry.emissivity import (
    Radiometry,
    radiance,
    recorrect_celsius,
    temperature_k,
)

RBF = Radiometry(R=22474.880859375, B=1520.0, F=1.0499999523162842)


def test_radiance_and_temperature_are_inverses() -> None:
    t = np.array([250.0, 293.15, 350.0, 500.0])
    assert np.allclose(temperature_k(radiance(t, RBF), RBF), t, atol=1e-6)


def test_same_parameters_is_the_identity() -> None:
    t_c = np.array([[15.0, 22.4], [88.3, 250.0]], dtype=np.float32)
    out = recorrect_celsius(t_c, RBF, eps_cam=0.95, trefl_cam_k=293.15, eps=0.95, trefl_k=293.15)
    assert np.allclose(out, t_c, atol=1e-4)


def test_lower_emissivity_raises_the_object_temperature_and_nan_passes_through() -> None:
    t_c = np.array([40.0, np.nan], dtype=np.float32)
    out = recorrect_celsius(t_c, RBF, eps_cam=0.95, trefl_cam_k=293.15, eps=0.30, trefl_k=293.15)
    assert out[0] > 40.0 + 5  # a shiny metal read at eps 0.95 is much hotter than shown
    assert np.isnan(out[1])
    # a hotter reflected background lowers the estimate at the same emissivity
    out2 = recorrect_celsius(t_c, RBF, eps_cam=0.95, trefl_cam_k=293.15, eps=0.30, trefl_k=330.0)
    assert out2[0] < out[0]


def test_reference_value_against_the_flir_formula() -> None:
    # Scene: true object 60 °C at eps 0.5 seen by a camera set to eps 0.95 / Trefl 20 °C.
    # W_meas = 0.5*W(333.15) + 0.5*W(293.15); the camera reports T((W_meas - 0.05*W(293.15))/0.95).
    w_meas = 0.5 * radiance(np.array([333.15]), RBF) + 0.5 * radiance(np.array([293.15]), RBF)
    reported_c = (
        temperature_k((w_meas - 0.05 * radiance(np.array([293.15]), RBF)) / 0.95, RBF) - 273.15
    )
    back = recorrect_celsius(
        reported_c.astype(np.float32),
        RBF,
        eps_cam=0.95,
        trefl_cam_k=293.15,
        eps=0.5,
        trefl_k=293.15,
    )
    assert back[0] == pytest.approx(60.0, abs=1e-3)  # recovers the true object temperature


def test_series_applies_roi_emissivity_and_documents_it(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from flir_research_interface.analysis.export import series_csv
    from flir_research_interface.analysis.series import parse_rois, roi_series
    from flir_research_interface.camera.base import Frame
    from flir_research_interface.playback.reader import ExperimentReader
    from flir_research_interface.recording.recorder import Recorder

    rec = Recorder(None, experiments_root=tmp_path, chunk_frames=4, min_free_gb=0.0)
    d = rec.start(
        name="e",
        metadata={},
        camera_info={
            "ir_format": "TemperatureLinear10mK",
            "object_parameters": {"ObjectEmissivity": 0.95, "ReflectedTemperature": 293.15},
            "calibration_constants": {"R": RBF.R, "B": RBF.B, "F": RBF.F},
        },
    )
    rec.submit(
        Frame(
            frame_id=0,
            device_timestamp_ns=0,
            host_timestamp_ns=0,
            pixel_format="Mono16",
            ir_format="TemperatureLinear10mK",
            counts=np.full((4, 4), 33315, np.uint16),
            incomplete=False,
        )
    )  # 60.00 °C as the camera reports it
    rec.stop()
    r = ExperimentReader(d)
    rois = parse_rois(
        '[{"id":1,"kind":"spot","x":1,"y":1},'
        '{"id":2,"kind":"spot","x":1,"y":1,"emissivity":0.5},'
        '{"id":3,"kind":"rect","x0":0,"y0":0,"x1":2,"y1":2,"emissivity":0.5,"reflected_c":40}]'
    )
    assert rois[1]["emissivity"] == 0.5 and rois[2]["reflected_c"] == 40
    s = roi_series(r, rois)["series"]
    assert s["1"]["value"][0] == pytest.approx(60.0, abs=0.01)
    assert s["2"]["value"][0] > 60.0 + 10
    assert s["3"]["mean"][0] < s["2"]["value"][0]  # hotter reflected background
    csv = series_csv(r, rois)
    assert "emissivity=0.5" in csv and "reflected_c=40" in csv
    with pytest.raises(ValueError):
        parse_rois('[{"id":1,"kind":"spot","x":1,"y":1,"emissivity":1.5}]')
