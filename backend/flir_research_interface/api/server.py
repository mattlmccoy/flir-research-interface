"""``fri-serve``: run the FastAPI service with uvicorn."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import uvicorn

from flir_research_interface.api.app import create_app
from flir_research_interface.visible.recorder import default_visible_factory


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
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    dotenv = Path(__file__).resolve().parents[2] / ".env"  # backend/.env (git-ignored)
    app = create_app(
        default_backend=args.backend,
        sim_fps=args.sim_fps,
        viz_fps=args.viz_fps,
        visible_factory=default_visible_factory(dotenv),
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
