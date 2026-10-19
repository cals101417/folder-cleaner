"""Remembers the user's last choices between launches (per-user JSON file)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .config import APP_NAME

DEFAULTS = {
    "folder": "",
    "keep_policy": "oldest",
    "dupe_min_size": "1 MB",
    "organize_mode": "type",
}


def _path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME / "settings.json"


class Settings(dict):
    def __init__(self):
        super().__init__(DEFAULTS)
        try:
            self.update(json.loads(_path().read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        try:
            path = _path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self, indent=2), encoding="utf-8")
        except OSError:
            pass  # settings are a convenience; never block the user over them
