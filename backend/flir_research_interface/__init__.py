"""FLIR Research Interface backend package."""

# Single source of truth for the app version. Bump on each shipped milestone (semver-ish:
# MINOR for features, PATCH for fixes). Surfaced by /api/health and shown in the UI status bar.
__version__ = "0.4.3"

__all__ = ["__version__"]
