"""Profile pictures: a small image data URL kept in the user's record, so it travels on the SSD.

The browser shrinks the photo before upload; the operator only checks type and size.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.storage import register_drive
from flir_research_interface.users import MAX_AVATAR_BYTES, USERS_FILE

PNG_1PX = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
    )
).decode()
GOOD = f"data:image/png;base64,{PNG_1PX}"


def _client(tmp_path: Path, drive: bool = False) -> tuple[Path, Path, TestClient]:
    root = tmp_path / "experiments"
    root.mkdir()
    mount = tmp_path / "SSD"
    if drive:
        mount.mkdir()
        register_drive(root, str(mount))
    app = create_app(default_backend="simulated", experiments_root=root, min_free_gb=0.0)
    c = TestClient(app)
    c.post("/api/users", json={"name": "Ana"})
    return root, mount / "FLIR-recordings", c


def test_upload_shows_in_the_user_list(tmp_path: Path) -> None:
    _root, _drive, c = _client(tmp_path)
    r = c.put("/api/users/ana/avatar", json={"image": GOOD})
    assert r.status_code == 200, r.text
    (ana,) = r.json()["users"]
    assert ana["avatar"] == GOOD
    assert c.get("/api/users").json()["users"][0]["avatar"] == GOOD


def test_no_picture_reads_as_null(tmp_path: Path) -> None:
    _root, _drive, c = _client(tmp_path)
    assert c.get("/api/users").json()["users"][0]["avatar"] is None


def test_remove_picture(tmp_path: Path) -> None:
    _root, _drive, c = _client(tmp_path)
    c.put("/api/users/ana/avatar", json={"image": GOOD})
    r = c.delete("/api/users/ana/avatar")
    assert r.status_code == 200
    assert r.json()["users"][0]["avatar"] is None


def test_refuses_non_images_and_oversize(tmp_path: Path) -> None:
    _root, _drive, c = _client(tmp_path)
    for bad in ("data:text/html;base64,PGI+", "data:image/png;base64,!!notb64"):
        assert c.put("/api/users/ana/avatar", json={"image": bad}).status_code == 400
    big = "data:image/jpeg;base64," + base64.b64encode(b"x" * (MAX_AVATAR_BYTES + 1)).decode()
    assert c.put("/api/users/ana/avatar", json={"image": big}).status_code == 413
    assert c.put("/api/users/nobody/avatar", json={"image": GOOD}).status_code == 404
    assert c.get("/api/users").json()["users"][0]["avatar"] is None


def test_picture_travels_on_the_ssd(tmp_path: Path) -> None:
    _root, drive, c = _client(tmp_path, drive=True)
    c.put("/api/users/ana/avatar", json={"image": GOOD})
    on_ssd = json.loads((drive / USERS_FILE).read_text())
    assert on_ssd["users"][0]["avatar"] == GOOD
