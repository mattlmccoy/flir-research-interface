"""``fri-thumbs``: (re)generate preview.png / keyframes.png for recorded experiments."""

from __future__ import annotations

import argparse
from pathlib import Path

from flir_research_interface.analysis.preview import generate_previews


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate experiment previews")
    p.add_argument(
        "root", nargs="?", default="experiments", help="experiments root or one experiment dir"
    )
    p.add_argument("--force", action="store_true", help="regenerate even if preview.png exists")
    args = p.parse_args(argv)
    root = Path(args.root)
    if (root / "metadata.json").is_file():
        dirs = [root]
    elif root.is_dir():
        dirs = sorted(d for d in root.iterdir() if d.is_dir())
    else:
        print(f"{root}: not found")
        return 2
    rc = 0
    for d in dirs:
        if not args.force and (d / "preview.png").is_file() and (d / "keyframes.png").is_file():
            print(f"{d.name}: up to date")
            continue
        try:
            out = generate_previews(d)
            frame_idx = out["preview"]["frame_index"]
            kf_count = out["keyframes"]["count"]
            print(f"{d.name}: preview frame {frame_idx}, {kf_count} keyframes ({out['units']})")
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"{d.name}: FAILED {type(exc).__name__}: {exc}")
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
