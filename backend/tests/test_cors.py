"""Deployment model (spec §6.3): the site UI talks to the local operator across origins.

* CORS allows exactly localhost/127.0.0.1 on any port plus the configured site origin.
* Browser-originated state-changing requests must carry ``X-FRI-Client: 1`` (forces a preflight
  so a random website cannot drive the camera). Non-browser clients (no ``Origin``) are local
  tools and are not affected.
* Chrome Local Network Access: preflights answer ``Access-Control-Allow-Private-Network: true``.
* ``/api/health`` carries ``api_version`` and ``app_version`` for the handshake.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from flir_research_interface import __version__
from flir_research_interface.api.app import API_VERSION, create_app
from flir_research_interface.camera.base import Frame
from flir_research_interface.recording.recorder import Recorder
from flir_research_interface.visible import full_range

SITE = "https://mattlmccoy.github.io"


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(default_backend="simulated", experiments_root=tmp_path, site_origin=SITE)
    )


def test_health_carries_versions(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        body = c.get("/api/health").json()
        assert body["api_version"] == API_VERSION and body["app_version"] == __version__
        assert body["status"] == "ok"


def test_preflight_from_localhost_and_site_is_allowed_with_private_network(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        for origin in ("http://localhost:5173", "http://127.0.0.1:8000", SITE):
            r = c.options(
                "/api/camera/disconnect",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "x-fri-client, content-type",
                    "Access-Control-Request-Private-Network": "true",
                },
            )
            assert r.status_code == 200, (origin, r.text)
            assert r.headers["access-control-allow-origin"] == origin
            assert "x-fri-client" in r.headers["access-control-allow-headers"].lower()
            assert r.headers["access-control-allow-private-network"] == "true"


def test_preflight_from_other_origins_is_refused(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        r = c.options(
            "/api/camera/disconnect",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        )
        assert "access-control-allow-origin" not in r.headers
        g = c.get("/api/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in g.headers


def test_browser_posts_need_the_client_header(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        no = c.post("/api/camera/disconnect", headers={"Origin": "http://localhost:5173"})
        assert no.status_code == 403 and "X-FRI-Client" in no.json()["detail"]
        yes = c.post(
            "/api/camera/disconnect",
            headers={"Origin": "http://localhost:5173", "X-FRI-Client": "1"},
        )
        assert yes.status_code == 200
        # GETs never need it; non-browser clients (no Origin) never need it
        assert c.get("/api/health", headers={"Origin": "http://localhost:5173"}).status_code == 200
        assert c.post("/api/camera/disconnect").status_code == 200
        # the operator-served UI is same-origin: Origin equals Host, no header needed
        same = c.post("/api/camera/disconnect", headers={"Origin": "http://testserver"})
        assert same.status_code == 200


def test_preflight_allows_put_for_calibration(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        r = c.options(
            "/api/calibration/visible",
            headers={
                "Origin": SITE,
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "x-fri-client, content-type",
            },
        )
        assert r.status_code == 200, r.text
        assert "PUT" in r.headers["access-control-allow-methods"]


def test_site_can_read_the_visible_range_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The site UI reads ``X-Visible-Range`` to say whether the shown video is range-corrected;
    a cross-origin response hides every header CORS does not expose."""
    monkeypatch.setattr(full_range, "resolve_ffmpeg", lambda: None)
    rec = Recorder(None, experiments_root=tmp_path, chunk_frames=4)
    run = rec.start(name="vis", metadata={}, camera_info={"ir_format": "TemperatureLinear10mK"})
    rec.submit(
        Frame(
            frame_id=1, device_timestamp_ns=1, host_timestamp_ns=1, pixel_format="Mono16",
            ir_format="TemperatureLinear10mK", counts=np.zeros((4, 4), dtype=np.uint16),
            incomplete=False,
        )
    )
    rec.stop()
    (run / "visible.mp4").write_bytes(b"raw")
    with _client(tmp_path) as c:
        r = c.get(f"/api/experiments/{run.name}/visible.mp4", headers={"Origin": SITE})
    assert r.headers["x-visible-range"] == "raw-untagged"
    exposed = [h.strip().lower() for h in r.headers["access-control-expose-headers"].split(",")]
    assert "x-visible-range" in exposed


def test_api_version_is_1_1_and_in_step_with_the_ui() -> None:
    """The handshake versions move together: a 1.0 operator then warns a 1.1 UI (minor)."""
    ui = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "operator.ts"
    match = re.search(r'export const UI_API_VERSION = "([^"]+)"', ui.read_text(encoding="utf-8"))
    assert match is not None
    assert API_VERSION == "1.1"
    assert match.group(1) == API_VERSION
