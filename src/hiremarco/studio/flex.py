"""Flex Pitch's first pass from the booth: the scale and the correction amount on every note of the take.

Logic does the tuning; ``scripts/flex_io.applescript apply`` selects the notes through the editor's own Edit menu,
sets Scale Quantize and Pitch Correction, and reads them back. Its root pop-up lists some roots with sharps and
some with flats (live map of 2026-10-29), so a root it does not find is tried once in the other spelling.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from hiremarco.studio.analyze import SHARP_TO_FLAT, split_key

SCRIPT = Path(__file__).with_name("scripts") / "flex_io.applescript"
AMOUNT = 80  # Pitch Correction: tight on held notes, glides and vibrato kept (the Melodyne-style center 80)


def _osascript(args: list[str]) -> str:
    done = subprocess.run(["osascript", str(SCRIPT), *args], capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[-300:] or f"flex_io exited {done.returncode}")
    return done.stdout.strip()


def first_pass(key: str, amount: int = AMOUNT, run: Callable[[list[str]], str] = _osascript) -> str:
    root, scale = split_key(key)
    try:
        return run(["apply", root, scale, str(amount)])
    except RuntimeError as missed:
        other = SHARP_TO_FLAT.get(root)
        if other is None or "menu item" not in str(missed):
            raise
        return run(["apply", other, scale, str(amount)])
