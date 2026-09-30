"""The camera's frame_id is the 16-bit GigE Vision block id: it wraps 65535 -> 1 (0 is reserved).

Captured from experiments/20260930_142445_Run (FLIR A70): ids ran 51659 .. 65535, 1 .. 5348 with a
34 ms step across the wrap (no frame lost), one real drop at 58329 -> 58331 (67 ms step), a pre-wrap
"RF ON" mark at 51780 and a post-wrap NUC at 4034. After the wrap the live view froze because
``wait_for_frame`` waited for an id greater than 65535. A camera reconnect restarts ids at 1, which
must stay distinguishable from a wrap.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np

from flir_research_interface.acquisition.service import AcquisitionService
from flir_research_interface.analysis import run_summary
from flir_research_interface.analysis.export import series_csv
from flir_research_interface.analysis.run_summary import plot_marks, write_run_summary
from flir_research_interface.camera.base import Frame
from flir_research_interface.camera.simulated import SimulatedCameraBackend, UniformScene
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.recording.arm import Armer
from flir_research_interface.recording.recorder import Recorder
from flir_research_interface.recording.trigger import EndCondition, StartCondition, TriggerSpec
from flir_research_interface.validation import frame_row, summarize_rows

WRAP_IDS = [65533, 65534, 65535, 1, 2, 3]


def _frame(fid: int, i: int = 0) -> Frame:
    return Frame(
        frame_id=fid,
        device_timestamp_ns=i * 33_333_333,
        host_timestamp_ns=i * 33_333_333 + 7,
        pixel_format="Mono16",
        ir_format="TemperatureLinear10mK",
        counts=np.full((8, 8), 29815 + i, dtype=np.uint16),
        incomplete=False,
    )


class _Scripted(SimulatedCameraBackend):
    """Yields the given ids; each id waits for its gate so the test controls arrival."""

    def __init__(self, ids: list[int]) -> None:
        super().__init__(scene=UniformScene(25.0), width=8, height=8)
        self.ids = ids
        self.gates = [threading.Event() for _ in ids]

    def frames(self) -> Iterator[Frame]:
        for i, (fid, gate) in enumerate(zip(self.ids, self.gates, strict=True)):
            while not gate.wait(0.01):
                if not self._connected:
                    return
            yield _frame(fid, i)
        while self._connected:
            time.sleep(0.01)


def _latest_becomes(svc: AcquisitionService, fid: int) -> None:
    end = time.monotonic() + 2.0
    while time.monotonic() < end:
        f = svc.latest()
        if f is not None and f.frame_id == fid:
            return
        time.sleep(0.005)
    raise AssertionError(f"latest never became {fid}")


def _wait_after(ids: list[int]) -> Frame | None:
    """Deliver ids[0], then ask for a frame after it while ids[1] arrives."""
    cam = _Scripted(ids)
    svc = AcquisitionService(cam)
    svc.connect(svc.enumerate()[0])
    svc.start()
    try:
        cam.gates[0].set()
        _latest_becomes(svc, ids[0])
        cam.gates[1].set()
        return svc.wait_for_frame(after_id=ids[0], timeout_s=1.0)
    finally:
        svc.disconnect()


def test_wait_for_frame_returns_the_frame_after_the_16_bit_wrap() -> None:
    f = _wait_after([65535, 1])
    assert f is not None and f.frame_id == 1


def test_wait_for_frame_returns_the_first_frame_after_a_camera_reconnect() -> None:
    f = _wait_after([5348, 1])  # reconnect restarts the counter
    assert f is not None and f.frame_id == 1


def _record(tmp_path: Path, ids: list[int], rois: list[dict[str, Any]] | None = None) -> Path:
    rec = Recorder(None, experiments_root=tmp_path, chunk_frames=4, min_free_gb=0.0)
    d = rec.start(
        name="wrap",
        metadata={},
        camera_info={"backend": "simulated", "ir_format": "TemperatureLinear10mK"},
        extra={"rois": rois} if rois else None,
    )
    for i, fid in enumerate(ids):
        rec.submit(_frame(fid, i))
        if fid == 2:
            rec.note_event("annotation", {"name": "RF ON", "note": "post-wrap"})
    rec.stop()
    return d


def test_recorder_reports_no_gap_across_the_wrap(tmp_path: Path) -> None:
    rec = Recorder(None, experiments_root=tmp_path, chunk_frames=4, min_free_gb=0.0)
    rec.start(name="w", metadata={}, camera_info={"backend": "simulated"})
    for i, fid in enumerate(WRAP_IDS):
        rec.submit(_frame(fid, i))
    summary = rec.stop()
    assert summary["frames_written"] == len(WRAP_IDS)
    assert summary["frame_id_gaps"] == 0 and summary["gap_events"] == []


def test_recorder_counts_a_frame_dropped_across_the_wrap(tmp_path: Path) -> None:
    rec = Recorder(None, experiments_root=tmp_path, chunk_frames=4, min_free_gb=0.0)
    rec.start(name="w", metadata={}, camera_info={"backend": "simulated"})
    for i, fid in enumerate([65533, 65534, 1, 2]):  # 65535 never arrived
        rec.submit(_frame(fid, i))
    summary = rec.stop()
    assert summary["frame_id_gaps"] == 1
    assert summary["gap_events"] == [{"after_frame_id": 65534, "missing": 1}]


def test_recorder_does_not_call_a_camera_reconnect_a_gap(tmp_path: Path) -> None:
    rec = Recorder(None, experiments_root=tmp_path, chunk_frames=4, min_free_gb=0.0)
    rec.start(name="w", metadata={}, camera_info={"backend": "simulated"})
    for i, fid in enumerate([5347, 5348, 1, 2]):
        rec.submit(_frame(fid, i))
    summary = rec.stop()
    assert summary["frame_id_gaps"] == 0 and summary["gap_events"] == []


def test_validation_frame_id_gaps_is_zero_across_the_wrap() -> None:
    rows = [frame_row(_frame(fid, i), t0_ns=0, spots=[], rois=[]) for i, fid in enumerate(WRAP_IDS)]
    assert summarize_rows(rows)["frame_id_gaps"] == 0


def test_pretrigger_count_includes_ring_frames_from_before_the_wrap() -> None:
    spec = TriggerSpec(
        start=StartCondition(kind="rf"),
        end=EndCondition(kind="rf"),
        pretrigger_s=1.0,
        max_seconds=10_000.0,
    )
    a = Armer(spec, rois=[], fps_hint=30.0)
    for i, fid in enumerate(WRAP_IDS):
        a.on_frame(_frame(fid, i))
    a.started_frame_id = 2  # the trigger fired on the frame with id 2

    class _Sink:
        def submit(self, frame: Frame) -> None:
            pass

    assert a.attach(_Sink()) == 4  # type: ignore[arg-type]  # 65533, 65534, 65535, 1


def test_plot_marks_after_the_wrap_land_on_their_own_frames() -> None:
    ids = list(range(51659, 65536)) + list(range(1, 5349))
    marks = [(51780, "RF ON"), (4034, "NUC (69 fr)")]
    assert run_summary.mark_indices(ids, marks) == [ids.index(51780), ids.index(4034)]


def test_plot_marks_pick_the_occurrence_after_the_previous_mark_when_ids_repeat() -> None:
    ids = list(range(1, 65536)) * 2  # a run longer than one 65535-frame cycle
    assert run_summary.mark_indices(ids, [(100, "a"), (50, "b")]) == [99, 65535 + 49]


def test_exports_cover_every_frame_of_a_wrapped_recording(tmp_path: Path) -> None:
    rois = [{"id": 1, "kind": "rect", "x0": 0, "y0": 0, "x1": 4, "y1": 4}]
    reader = ExperimentReader(_record(tmp_path, WRAP_IDS, rois))
    out = write_run_summary(reader)
    assert Path(out["readme"]).is_file() and out["roi_plot"] and Path(out["roi_plot"]).is_file()
    body = [ln for ln in series_csv(reader, rois).splitlines() if ln and not ln.startswith("#")]
    assert [int(r.split(",")[1]) for r in body[1:]] == WRAP_IDS  # header row, then every frame
    t = [float(r.split(",")[0]) for r in body[1:]]
    assert t == sorted(t) and t[-1] > 0
    marks = plot_marks(reader)
    assert marks == [(2, "RF ON")]
    assert run_summary.mark_indices(reader.timeline()["frame_id"], marks) == [4]
