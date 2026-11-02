"""Marco's running log: one plain line per step, all day, for the window the film watches.

Every line names what did the step first (a model id such as muse-spark-1.3,
or ``marco`` for his own code), then the step in plain words, then the seconds
it took. The lines go to ``~/.local/state/hiremarco/marco.log`` as JSON, newest
last; ``marco log`` prints the tail and ``marco log --window`` shows the last
eight in a fixed dark window (Director's format, 2026-11-02). Nothing private
goes in: an email, a phone number, a key-shaped token or a bearer line is
replaced before it is written, and no prompt text is ever passed here.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from hiremarco import config

MARCO = "marco"
NAME = "marco.log"
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
KEY = re.compile(r"\b(?=[A-Za-z0-9_-]{24,}\b)(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]+\b")
BEARER = re.compile(r"(?i)bearer\s+\S+")


def path() -> Path:
    return Path(config.STATE_DIR) / NAME


def clean(text: str) -> str:
    """The text with anything private replaced: an address, a number long enough to be a phone, a key-shaped
    token, a bearer line."""
    text = BEARER.sub("[bearer]", text)
    text = EMAIL.sub("[email]", text)
    text = KEY.sub("[key]", text)
    text = PHONE.sub("[number]", text)
    return " ".join(text.split())


def say(model: str, text: str, seconds: float | None = None, *, at: Path | None = None) -> dict:
    """One line: who did the step, the step in plain words, how long it took."""
    row = {"ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
           "model": (model or MARCO).strip(), "text": clean(text)[:200]}
    if seconds is not None:
        row["seconds"] = round(float(seconds), 1)
    target = at or path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def tail(n: int = 8, *, at: Path | None = None) -> list[dict]:
    target = at or path()
    if not target.exists():
        return []
    lines = target.read_text().splitlines()
    rows = []
    for line in lines[-n:]:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def line(row: dict) -> str:
    """A row as one printed line: model, step, seconds."""
    took = f"  {row['seconds']:.1f} s" if "seconds" in row else ""
    return f"{row['model']:<24} {row['text']}{took}"


class Steps:
    """A log callback that also streams: every line it is given goes to the file as Marco's own step, timed
    from the previous line; ``as_model`` tags the next lines with the model that produced them."""

    def __init__(self, also: Callable[[str], None] | None = print, model: str = MARCO, at: Path | None = None):
        self.also = also
        self.model = model
        self.at = at
        self.last = time.monotonic()

    def __call__(self, text: str) -> None:
        if self.also:
            self.also(text)
        now = time.monotonic()
        words = text.strip()
        if words:
            say(self.model, words, now - self.last, at=self.at)
        self.last = now

    def as_model(self, model: str) -> None:
        self.model = model or MARCO
