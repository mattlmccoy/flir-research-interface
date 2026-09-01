"""RTSP access to the A50/A70 visible camera and display streams.

Endpoints from FLIR user manual T810579 §9 ("RTSP Streams"). The camera requires its web-UI
login (calibration certificate) for every RTSP DESCRIBE. Credentials are read from a local
``.env`` file or environment variables and are never logged: every printed URL is redacted.

This subsystem is deliberately separate from the radiometric GigE pipeline (brief §24): the RTSP
video is compressed display/visible imagery, never measurement data.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

RTSP_PATHS: dict[str, str] = {
    "display_h264": "/avc/",
    "display_h264_no_overlay": "/avc/?overlay=off",
    "display_mpeg4": "/mpeg4/",
    "display_mjpeg": "/mjpg/",
    "visible_full": "/avc/ch1",
    "visible_full_mpeg4": "/mpeg4/ch1",
    "visible_full_mjpeg": "/mjpg/ch1",
}
"""Manual T810579 §9: ``/`` = web-UI image (IR/visual/MSX/FSX, 640x480); ``/ch1`` = 1280x960."""

ENV_HOST = "FRI_CAMERA_HOST"
ENV_USER = "FRI_RTSP_USER"
ENV_PASSWORD = "FRI_RTSP_PASSWORD"  # noqa: S105 - variable name, not a secret
FFPROBE_CANDIDATES = (
    "ffprobe",
    "/opt/homebrew/opt/ffmpeg@6/bin/ffprobe",
    "/opt/homebrew/bin/ffprobe",
)


def build_rtsp_url(
    host: str, path: str, *, user: str | None = None, password: str | None = None
) -> str:
    """``rtsp://[user:password@]host/path`` with credentials percent-encoded."""
    auth = ""
    if user:
        auth = quote(user, safe="")
        if password is not None:
            auth += ":" + quote(password, safe="")
        auth += "@"
    return f"rtsp://{auth}{host}{path}"


def redact_url(url: str) -> str:
    """Replace the password in an RTSP URL with ``***`` (safe for logs and reports)."""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    host = parts.hostname or ""
    if parts.port:
        host += f":{parts.port}"
    netloc = f"{parts.username}:***@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def load_dotenv(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE loader (comments/blank lines ignored, optional quotes). No dependency."""
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            env[key] = value
    return env


def credentials(dotenv: Path | None = None) -> tuple[str | None, str | None, str | None]:
    """(host, user, password) from environment, falling back to ``dotenv``."""
    file_env = load_dotenv(dotenv) if dotenv else {}

    def get(name: str) -> str | None:
        return os.environ.get(name) or file_env.get(name) or None

    return get(ENV_HOST), get(ENV_USER), get(ENV_PASSWORD)


def find_ffprobe() -> str | None:
    for c in FFPROBE_CANDIDATES:
        p = shutil.which(c) if "/" not in c else (c if Path(c).is_file() else None)
        if p:
            return p
    return None


def parse_ffprobe_json(raw: str) -> dict[str, Any]:
    """Extract the first video stream from ``ffprobe -of json`` output."""
    data = json.loads(raw)
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            fps = None
            for key in ("r_frame_rate", "avg_frame_rate"):
                num, _, den = str(s.get(key, "0/0")).partition("/")
                try:
                    if int(den) and int(num):
                        fps = int(num) / int(den)
                        break
                except ValueError:
                    continue
            return {
                "codec": s.get("codec_name"),
                "width": s.get("width"),
                "height": s.get("height"),
                "fps": fps,
                "pix_fmt": s.get("pix_fmt"),
            }
    raise ValueError("no video stream in ffprobe output")


def probe_stream(url: str, *, ffprobe: str, timeout_s: float = 20.0) -> dict[str, Any]:
    """Run ffprobe over TCP and return parsed stream info. Errors carry the redacted URL only."""
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-rtsp_transport",
        "tcp",
        "-rw_timeout",
        "8000000",
        "-show_entries",
        "stream=codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,pix_fmt",
        "-of",
        "json",
        url,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"ffprobe timed out for {redact_url(url)}") from exc
    if r.returncode != 0 or not r.stdout.strip():
        err = r.stderr.replace(url, redact_url(url)).strip()
        raise RuntimeError(f"ffprobe failed for {redact_url(url)}: {err[:300]}")
    return parse_ffprobe_json(r.stdout)


def main(argv: list[str] | None = None) -> int:
    """CLI ``fri-rtsp-check``: probe the camera's RTSP endpoints using local credentials."""
    p = argparse.ArgumentParser(
        description="Probe FLIR A50/A70 RTSP streams (credentials from .env)"
    )
    p.add_argument("--host", default=None, help=f"camera IP/hostname (or env {ENV_HOST})")
    p.add_argument(
        "--dotenv", default=".env", help="path to .env with FRI_RTSP_USER / FRI_RTSP_PASSWORD"
    )
    p.add_argument(
        "--path",
        action="append",
        default=None,
        help=(
            f"RTSP path(s) to probe; default: {RTSP_PATHS['visible_full']} "
            f"and {RTSP_PATHS['display_h264']}"
        ),
    )
    args = p.parse_args(argv)

    env_host, user, password = credentials(Path(args.dotenv))
    host = args.host or env_host
    if not host:
        print(f"camera host missing: pass --host or set {ENV_HOST} in {args.dotenv}")
        return 2
    if not user or password is None:
        print(
            f"credentials missing: put {ENV_USER}=... and {ENV_PASSWORD}=... in {args.dotenv} "
            "(the camera's web-UI login from its calibration certificate). "
            "That file is git-ignored."
        )
        return 2
    ffprobe = find_ffprobe()
    if not ffprobe:
        print("ffprobe not found (macOS: brew install ffmpeg@6)")
        return 2
    paths = args.path or [RTSP_PATHS["visible_full"], RTSP_PATHS["display_h264"]]
    rc = 0
    for path in paths:
        url = build_rtsp_url(host, path, user=user, password=password)
        try:
            info = probe_stream(url, ffprobe=ffprobe)
            print(f"{redact_url(url)} -> {info}")
        except (RuntimeError, ValueError) as exc:
            print(f"{redact_url(url)} -> ERROR {exc}")
            rc = 1
    return rc


__all__ = [
    "ENV_HOST",
    "ENV_PASSWORD",
    "ENV_USER",
    "RTSP_PATHS",
    "build_rtsp_url",
    "credentials",
    "find_ffprobe",
    "load_dotenv",
    "main",
    "parse_ffprobe_json",
    "probe_stream",
    "redact_url",
]
