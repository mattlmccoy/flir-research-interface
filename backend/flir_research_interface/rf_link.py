"""RF-link: receive RF on/off events from the T&C tool and own the recording policy.

Pure settings + pure decision logic; the FastAPI wiring lives in api/app.py. Settings persist to
a git-ignored ``.rf_link.json`` sidecar in the experiments root, mirroring storage.py's pattern.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_NAME = ".rf_link.json"


@dataclass(frozen=True)
class RfLinkSettings:
    auto_start_on_rf_on: bool = True
    stop_on_rf_off: bool = False  # False = keep recording for cooldown


def load_settings(root: Path) -> RfLinkSettings:
    path = Path(root) / CONFIG_NAME
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return RfLinkSettings()
    return RfLinkSettings(
        auto_start_on_rf_on=bool(data.get("auto_start_on_rf_on", True)),
        stop_on_rf_off=bool(data.get("stop_on_rf_off", False)),
    )


def save_settings(root: Path, settings: RfLinkSettings) -> None:
    Path(root).mkdir(parents=True, exist_ok=True)
    (Path(root) / CONFIG_NAME).write_text(json.dumps(asdict(settings), indent=2))


@dataclass(frozen=True)
class RfAction:
    mark: bool
    start: bool
    stop: bool


def plan_rf_action(*, state: str, is_recording: bool, link_owns: bool,
                   settings: RfLinkSettings) -> RfAction:
    """Decide what to do for an RF event. Pure; the caller performs the effects."""
    if state == "on":
        return RfAction(
            mark=True,
            start=settings.auto_start_on_rf_on and not is_recording,
            stop=False,
        )
    # state == "off"
    return RfAction(
        mark=True,
        start=False,
        stop=settings.stop_on_rf_off and is_recording and link_owns,
    )
