"""``fri-serve``: run the FastAPI service with uvicorn."""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Mapping
from pathlib import Path

import uvicorn

from flir_research_interface.api.app import create_app
from flir_research_interface.visible.preview import default_preview_factory
from flir_research_interface.visible.recorder import default_visible_factory
from flir_research_interface.visible.rtsp import load_dotenv

logger = logging.getLogger(__name__)
EXPERIMENTS_ROOT_ENV = "FRI_EXPERIMENTS_ROOT"


def resolve_experiments_root(
    env: Mapping[str, str], file_env: Mapping[str, str]
) -> str | None:
    """The experiments directory from ``FRI_EXPERIMENTS_ROOT`` — the process environment first, then
    the git-ignored ``.env``. Blank/whitespace is treated as unset (caller keeps its default). This
    lets the data live outside the checkout (e.g. a Dropbox folder) and survive updates, since
    ``.env`` is never touched by ``git pull``."""
    for src in (env, file_env):
        v = src.get(EXPERIMENTS_ROOT_ENV)
        if v and v.strip():
            return v.strip()
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="FLIR Research Interface service")
    p.add_argument(
        "--host", default="127.0.0.1", help="bind address (LAN exposure is Milestone 10)"
    )
    p.add_argument("--port", type=int, default=8000)
    p.add_argument(
        "--backend",
        default="simulated",
        choices=["simulated", "spinnaker"],
        help="default backend for /api/camera/devices",
    )
    p.add_argument("--viz-fps", type=float, default=15.0, help="max WebSocket frame rate")
    p.add_argument("--sim-fps", type=float, default=30.0)
    p.add_argument(
        "--site-origin",
        default="https://mattlmccoy.github.io",
        help="origin of the GitHub Pages site allowed to drive this operator (CORS); '' to disable",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    dotenv = Path(__file__).resolve().parents[2] / ".env"  # backend/.env (git-ignored)
    exp_root = resolve_experiments_root(os.environ, load_dotenv(dotenv) if dotenv.exists() else {})
    if exp_root is not None:
        logger.info("experiments root: %s", exp_root)
    app = create_app(
        default_backend=args.backend,
        sim_fps=args.sim_fps,
        viz_fps=args.viz_fps,
        visible_factory=default_visible_factory(dotenv),
        site_origin=args.site_origin or None,
        preview_factory=default_preview_factory(dotenv),
        experiments_root=Path(exp_root) if exp_root else None,
        autoconnect=True,  # operator auto-connects the real camera on startup + auto-reconnects
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
