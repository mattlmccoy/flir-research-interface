#!/usr/bin/env python
"""Thin wrapper so the probe can be run as ``python scripts/camera_probe.py``.

Equivalent to the ``fri-probe`` console script installed with the backend package.
"""

from flir_research_interface.probe import main

if __name__ == "__main__":
    raise SystemExit(main())
