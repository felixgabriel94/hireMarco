"""Settings and secrets.

Secrets live in one file outside the repository, ``~/.config/hiremarco/env``
(override with ``HIREMARCO_ENV``), in ``KEY=value`` lines. Nothing here prints
a value; ``describe()`` reports only which keys are present.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ENV_PATH = Path.home() / ".config" / "hiremarco" / "env"
STATE_DIR = Path(os.environ.get("HIREMARCO_STATE", Path.home() / ".local" / "state" / "hiremarco"))

KNOWN_KEYS = (
    "MODEL_API_KEY",            # Meta Model API, https://api.meta.ai/v1
    "WHATSAPP_TOKEN",           # WhatsApp Cloud API system-user token
    "WHATSAPP_PHONE_NUMBER_ID", # the business phone number id Marco sends from
    "WHATSAPP_VERIFY_TOKEN",    # webhook verification handshake
    "WHATSAPP_APP_SECRET",      # webhook signature check
    "OWNER_WHATSAPP",           # the Owner's number, E.164 without plus
)


def env_path() -> Path:
    return Path(os.environ.get("HIREMARCO_ENV", DEFAULT_ENV_PATH))


def load_env(path: Path | None = None) -> dict[str, str]:
    """Read ``KEY=value`` lines. Missing file means no secrets, not an error."""
    path = path or env_path()
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get(key: str, path: Path | None = None) -> str | None:
    """Process environment first, then the env file."""
    return os.environ.get(key) or load_env(path).get(key)


def require(key: str, path: Path | None = None) -> str:
    value = get(key, path)
    if not value:
        raise KeyError(f"{key} is not set; add it to {path or env_path()}")
    return value


def describe(path: Path | None = None) -> dict[str, bool]:
    """Which known keys are present. Values are never returned."""
    return {k: bool(get(k, path)) for k in KNOWN_KEYS}
