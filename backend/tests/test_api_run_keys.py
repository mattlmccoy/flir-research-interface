"""Job records and render locks of a run inside a collection are keyed by ``RunRef.key``.

The runs are synthetic recordings made with ``Recorder`` (``smart_recording``, never PySpin):
the frames are hand-made, the store layout is the real one. The ``rf-sintering`` copy is a
``copytree`` of the same run, so both collections hold a run with the same name.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from smart_recording import SMART, blob_celsius, make_smart_run, to_counts

from flir_research_interface.api.app import create_app
from flir_research_interface.camera.base import Frame
from flir_research_interface.concurrency import KeyedLocks
from flir_research_interface.recording.recorder import Recorder


def _client(root: Path) -> TestClient:
    return TestClient(
        create_app(default_backend="simulated", experiments_root=root, min_free_gb=0.0)
    )


def _no_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    # Same with or without ffmpeg on the machine: no video renders.
    from flir_research_interface.analysis import media, thermal_video

    monkeypatch.setattr(thermal_video, "find_ffprobe", lambda *_a, **_k: None)
    monkeypatch.setattr(media, "find_ffprobe", lambda *_a, **_k: None)


def _wait_idle(c: TestClient, timeout_s: float = 60.0) -> None:
    t0 = time.monotonic()
    while c.app.state.render_tasks and time.monotonic() - t0 < timeout_s:  # type: ignore[attr-defined]
        time.sleep(0.05)
    assert not c.app.state.render_tasks  # type: ignore[attr-defined]


def test_stored_smart_roi_jobs_keyed_by_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_ffmpeg(monkeypatch)
    root = tmp_path / "experiments"
    d = make_smart_run(root / "mattmccoy", n=6)
    name = d.name
    shutil.copytree(d, root / "rf-sintering" / name)  # same name, no smart series computed
    with _client(root) as c:
        r = c.post(f"/api/experiments/{name}/export/derived?collection=mattmccoy&video=false")
        assert r.status_code == 200, r.text
        _wait_idle(c)
        assert c.app.state.derived_jobs[f"mattmccoy/{name}"]["state"] == "done"  # type: ignore[attr-defined]
        smart_jobs: dict[Any, Any] = c.app.state.smart_jobs  # type: ignore[attr-defined]
        assert (f"mattmccoy/{name}", SMART["id"]) in smart_jobs
        url = f"/api/experiments/{name}/smart-roi/{SMART['id']}/status"
        assert c.get(url + "?collection=rf-sintering").json()["state"] == "idle"
        assert c.get(url + "?collection=mattmccoy").json()["state"] == "done"


class _SpyLocks(KeyedLocks):
    def __init__(self) -> None:
        super().__init__()
        self.keys: list[str] = []

    def get(self, key: str) -> Any:
        self.keys.append(key)
        return super().get(key)


def test_post_stop_render_lock_keyed_by_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_ffmpeg(monkeypatch)
    root = tmp_path / "experiments"
    # A recorder writing into a collection (recording there via the API is Task 5).
    rec = Recorder(None, experiments_root=root / "mattmccoy", chunk_frames=4)
    d = rec.start(
        name="smart", metadata={},
        camera_info={"backend": "simulated", "ir_format": "TemperatureLinear10mK", "model": "Sim"},
        extra={"rois": [SMART]},
    )
    for i in range(4):
        rec.submit(Frame(
            frame_id=100 + i, device_timestamp_ns=1_000_000_000 + i * 33_000_000,
            host_timestamp_ns=5_000_000_000 + i * 33_000_000, pixel_format="Mono16",
            ir_format="TemperatureLinear10mK", counts=to_counts(blob_celsius(i)),
            incomplete=False,
        ))
    with _client(root) as c:
        spy = _SpyLocks()
        c.app.state.render_locks = spy  # type: ignore[attr-defined]
        c.app.state.recorder = rec  # type: ignore[attr-defined]
        assert c.post("/api/recording/stop").status_code == 200
        _wait_idle(c)
        assert f"mattmccoy/{d.name}" in spy.keys, spy.keys
        smart_jobs: dict[Any, Any] = c.app.state.smart_jobs  # type: ignore[attr-defined]
        assert (f"mattmccoy/{d.name}", SMART["id"]) in smart_jobs
