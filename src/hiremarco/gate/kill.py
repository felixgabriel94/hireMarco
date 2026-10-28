"""The kill switch: one file in the state folder. Present means every action
and every model call is refused until it is removed.

    uv run marco gate kill on
    uv run marco gate kill off
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from hiremarco import config


def kill_path() -> Path:
    return Path(os.environ.get("HIREMARCO_STATE", config.STATE_DIR)) / "kill-switch"


def kill_switch_on() -> bool:
    return kill_path().exists()


def set_kill_switch(on: bool, reason: str = "") -> None:
    path = kill_path()
    if on:
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        path.write_text(f"{stamp} {reason}".strip() + "\n")
    elif path.exists():
        path.unlink()
