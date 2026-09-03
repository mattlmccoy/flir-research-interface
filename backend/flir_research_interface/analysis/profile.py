"""Project profile: the experiment-specific parts of the UI, kept out of the tool itself.

A profile names the metadata fields the record panel asks for and the mark buttons (with
optional hotkeys) shown while recording. It lives on the operator
(``<experiments_root>/calibration/profile.json``) so every browser sees the same one, and each
recording's ``metadata.json`` stamps the profile name and mark labels. The data format never
depends on it: metadata stays a free dictionary and marks stay named events.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from flir_research_interface.analysis.calibration import calibration_dir

FILE_NAME = "profile.json"
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
FIELD_TYPES = ("text", "number")

DEFAULT_PROFILE: dict[str, Any] = {
    "name": "default",
    "fields": [
        {"key": "operator", "label": "Operator", "type": "text"},
        {"key": "sample_id", "label": "Sample ID", "type": "text"},
        {"key": "notes", "label": "Notes", "type": "text"},
    ],
    "marks": [{"label": "event A", "key": "a"}, {"label": "event B", "key": "b"}],
}


def validate_profile(doc: Any) -> dict[str, Any]:
    if not isinstance(doc, dict):
        raise ValueError("profile must be an object")
    name = doc.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 60:
        raise ValueError("profile name must be 1-60 characters")
    fields_in = doc.get("fields", [])
    marks_in = doc.get("marks", [])
    if not isinstance(fields_in, list) or not isinstance(marks_in, list):
        raise ValueError("fields and marks must be lists")
    if len(fields_in) > 40 or len(marks_in) > 12:
        raise ValueError("at most 40 fields and 12 marks")
    fields: list[dict[str, str]] = []
    seen: set[str] = set()
    for f in fields_in:
        if not isinstance(f, dict):
            raise ValueError("each field must be an object")
        key, label, ftype = f.get("key"), f.get("label"), f.get("type", "text")
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise ValueError(f"field key {key!r}: lowercase letters, digits, underscores only")
        if key in seen:
            raise ValueError(f"duplicate field key {key!r}")
        seen.add(key)
        if not isinstance(label, str) or not label.strip() or len(label) > 60:
            raise ValueError(f"field {key!r} needs a label")
        if ftype not in FIELD_TYPES:
            raise ValueError(f"field {key!r} type must be one of {FIELD_TYPES}")
        fields.append({"key": key, "label": label.strip(), "type": ftype})
    marks: list[dict[str, str]] = []
    for m in marks_in:
        if not isinstance(m, dict):
            raise ValueError("each mark must be an object")
        label, hot = m.get("label"), m.get("key")
        if not isinstance(label, str) or not label.strip() or len(label) > 40:
            raise ValueError("each mark needs a label (1-40 characters)")
        out: dict[str, str] = {"label": label.strip()}
        if hot is not None:
            if not isinstance(hot, str) or len(hot) != 1 or not hot.isalnum():
                raise ValueError(f"mark {label!r}: hotkey must be a single letter or digit")
            out["key"] = hot.lower()
        marks.append(out)
    return {"name": name.strip(), "fields": fields, "marks": marks}


def load_profile(experiments_root: Path) -> dict[str, Any]:
    path = calibration_dir(experiments_root) / FILE_NAME
    if not path.is_file():
        return DEFAULT_PROFILE
    try:
        return validate_profile(json.loads(path.read_text()))
    except (OSError, ValueError, json.JSONDecodeError):
        return DEFAULT_PROFILE


def save_profile(experiments_root: Path, doc: Any) -> dict[str, Any]:
    clean = validate_profile(doc)
    d = calibration_dir(experiments_root)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / (FILE_NAME + ".tmp")
    tmp.write_text(json.dumps(clean, indent=2))
    tmp.replace(d / FILE_NAME)
    return clean


__all__ = ["DEFAULT_PROFILE", "load_profile", "save_profile", "validate_profile"]
