"""Tests for the hardware-independent parts of the Milestone-1 camera probe."""

from __future__ import annotations

import json

from flir_research_interface.probe import (
    RADIOMETRY_KEYWORDS,
    is_radiometry_related,
    run_simulated_probe,
    summarize_counts,
)


def test_summarize_counts_reports_min_max_center() -> None:
    import numpy as np

    counts = np.arange(12, dtype=np.uint16).reshape(3, 4)
    summary = summarize_counts(counts)
    assert summary["width"] == 4 and summary["height"] == 3
    assert summary["min"] == 0 and summary["max"] == 11
    # center pixel = (y=1, x=2) -> value 6
    assert summary["center_xy"] == [2, 1]
    assert summary["center_value"] == 6


def test_radiometry_keyword_filter_catches_known_and_unknown_spellings() -> None:
    for name in [
        "IRFormat",
        "ObjectEmissivity",
        "ReflectedTemperature",
        "NUCMode",
        "CalibrationCase",
        "TemperatureLinearResolution",
        "AtmosphericTemperature",
        "RelativeHumidity",
        "ObjectDistance",
        "ExtOpticsTransmission",
        "SensorRange",
    ]:
        assert is_radiometry_related(name), name
    for name in ["Width", "Height", "PixelFormat", "AcquisitionMode", "GevSCPSPacketSize"]:
        assert not is_radiometry_related(name), name
    assert "emiss" in {k.lower() for k in RADIOMETRY_KEYWORDS}


def test_simulated_probe_report_is_json_serializable_and_complete() -> None:
    report = run_simulated_probe()
    text = json.dumps(report)  # must not raise
    assert '"backend": "simulated"' in text
    for key in ["probe_version", "host", "backend", "device", "camera_info", "frame"]:
        assert key in report, key
    frame = report["frame"]
    assert frame["pixel_format"] == "Mono16"
    assert frame["ir_format"] == "TemperatureLinear10mK"
    assert frame["width"] == 640 and frame["height"] == 480
    assert frame["frame_id"] == 0
    # temperature is DERIVED and labelled as such, never silently swapped for counts
    assert "center_temperature_c" in frame
    assert "counts_to_celsius_rule" in frame
