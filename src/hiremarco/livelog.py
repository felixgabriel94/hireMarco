"""Marco's live log: one short line per thing he does, written for the camera.

    heard: more reverb > reverb +1 step > 1.8 s

The Terminal that shows it holds nothing else, at 24 pt or larger.
"""

from __future__ import annotations

import sys
import time
from typing import TextIO


class Trace:
    def __init__(self, first: str, out: TextIO | None = None):
        self.parts = [first]
        self.out = out or sys.stdout
        self.started = time.monotonic()

    def add(self, part: str) -> "Trace":
        self.parts.append(part)
        return self

    def line(self) -> str:
        elapsed = time.monotonic() - self.started
        return " > ".join(self.parts + [f"{elapsed:.1f} s"])

    def done(self, last: str | None = None) -> str:
        if last:
            self.add(last)
        text = self.line()
        print(text, file=self.out, flush=True)
        return text
