"""Tests for RTSP URL/credential handling (visible camera subsystem)."""

from __future__ import annotations

from pathlib import Path

import pytest

from flir_research_interface.visible.rtsp import (
    RTSP_PATHS,
    build_rtsp_url,
    load_dotenv,
    parse_ffprobe_json,
    redact_url,
)


def test_paths_match_manual_t810579() -> None:
    assert RTSP_PATHS["visible_full"] == "/avc/ch1"
    assert RTSP_PATHS["display_h264"] == "/avc/"
    assert RTSP_PATHS["display_h264_no_overlay"] == "/avc/?overlay=off"


def test_build_url_percent_encodes_credentials() -> None:
    url = build_rtsp_url("192.168.7.2", "/avc/ch1", user="admin", password="p@ss:w/rd#1")
    assert url == "rtsp://admin:p%40ss%3Aw%2Frd%231@192.168.7.2/avc/ch1"


def test_build_url_without_credentials() -> None:
    assert build_rtsp_url("cam.local", "/avc/") == "rtsp://cam.local/avc/"


def test_redact_hides_password_but_keeps_user_and_host() -> None:
    url = build_rtsp_url("192.168.7.2", "/avc/ch1", user="admin", password="secret")
    assert redact_url(url) == "rtsp://admin:***@192.168.7.2/avc/ch1"
    assert "secret" not in redact_url(url)


def test_load_dotenv_parses_simple_file_and_ignores_comments(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text('# camera\nFRI_RTSP_USER=admin\nFRI_RTSP_PASSWORD="a b"\nEMPTY=\n\nBAD LINE\n')
    env = load_dotenv(f)
    assert env == {"FRI_RTSP_USER": "admin", "FRI_RTSP_PASSWORD": "a b", "EMPTY": ""}


def test_load_dotenv_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_dotenv(tmp_path / "nope") == {}


def test_parse_ffprobe_json_extracts_video_stream() -> None:
    raw = (
        '{"streams":[{"codec_type":"video","codec_name":"h264","width":1280,"height":960,'
        '"r_frame_rate":"30/1","avg_frame_rate":"0/0","pix_fmt":"yuvj420p"}],'
        '"format":{"format_name":"rtsp"}}'
    )
    info = parse_ffprobe_json(raw)
    assert info == {
        "codec": "h264",
        "width": 1280,
        "height": 960,
        "fps": 30.0,
        "pix_fmt": "yuvj420p",
    }


def test_parse_ffprobe_json_without_video_raises() -> None:
    with pytest.raises(ValueError, match="no video stream"):
        parse_ffprobe_json('{"streams":[]}')


def test_find_ffprobe_skips_candidates_that_do_not_run(tmp_path: Path) -> None:
    from flir_research_interface.visible.rtsp import find_ffprobe

    broken = tmp_path / "broken"
    broken.write_text("#!/bin/sh\necho 'dyld: Library not loaded' >&2\nexit 1\n")
    good = tmp_path / "good"
    good.write_text("#!/bin/sh\necho 'ffprobe version 6.1.6'\n")
    for f in (broken, good):
        f.chmod(0o755)
    assert find_ffprobe(candidates=(str(broken), str(good))) == str(good)
    assert find_ffprobe(candidates=(str(broken),)) is None


# ----------------------------------------------------------------------------- raw Digest client


def test_digest_response_matches_rfc2617_example_vector() -> None:
    from flir_research_interface.visible.rtsp import digest_response

    # RFC 2617 §3.5 worked example (qop=auth)
    resp = digest_response(
        user="Mufasa",
        password="Circle Of Life",
        realm="testrealm@host.com",
        method="GET",
        uri="/dir/index.html",
        nonce="dcd98b7102dd2f0e8b11d0f600bfb0c093",
        qop="auth",
        nc="00000001",
        cnonce="0a4f113b",
    )
    assert resp == "6629fae49393a05397450978507c4ef1"


def test_digest_response_without_qop_uses_rfc2069_form() -> None:
    import hashlib

    from flir_research_interface.visible.rtsp import digest_response

    ha1 = hashlib.md5(b"u:GStreamer RTSP Server:p").hexdigest()
    ha2 = hashlib.md5(b"DESCRIBE:rtsp://h/avc/ch1").hexdigest()
    expected = hashlib.md5(f"{ha1}:abc:{ha2}".encode()).hexdigest()
    assert (
        digest_response(
            user="u",
            password="p",
            realm="GStreamer RTSP Server",
            method="DESCRIBE",
            uri="rtsp://h/avc/ch1",
            nonce="abc",
            qop=None,
        )
        == expected
    )


def test_parse_www_authenticate_digest_challenge() -> None:
    from flir_research_interface.visible.rtsp import parse_digest_challenge

    hdr = 'Digest realm="GStreamer RTSP Server", nonce="5830bb66c652baff"'
    assert parse_digest_challenge(hdr) == {
        "realm": "GStreamer RTSP Server",
        "nonce": "5830bb66c652baff",
    }
    hdr2 = 'Digest realm="r", nonce="n", qop="auth,auth-int", algorithm=MD5, stale=FALSE'
    ch = parse_digest_challenge(hdr2)
    assert ch["qop"] == "auth,auth-int" and ch["algorithm"] == "MD5"


def test_parse_rtsp_response_splits_status_headers_body() -> None:
    from flir_research_interface.visible.rtsp import parse_rtsp_response

    raw = (
        b"RTSP/1.0 401 Unauthorized\r\nCSeq: 2\r\n"
        b'WWW-Authenticate: Digest realm="x", nonce="y"\r\n\r\n'
    )
    status, headers, body = parse_rtsp_response(raw)
    assert status == 401 and headers["www-authenticate"].startswith("Digest") and body == b""
    raw_ok = b"RTSP/1.0 200 OK\r\nCSeq: 3\r\nContent-Length: 5\r\n\r\nv=0\r\n"
    status, headers, body = parse_rtsp_response(raw_ok)
    assert status == 200 and body == b"v=0\r\n"
