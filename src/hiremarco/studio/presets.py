"""Channel strip presets: "Marco, my adlib preset" loads that Performance on the selected track.

The list is read from disk, not the screen: Logic keeps each saved track
Performance as a ``.cst`` file named exactly as its menu item, in
``~/Music/Audio Music Apps/Channel Strip Settings/Track/Performance``. A
spoken name matches one of those files or nothing; Marco never guesses a
preset that is not there.

Loading goes through Logic's own Setting menu by keyboard, the same keys
in the same order every time (``scripts/load_preset.applescript``): open the
selected track's Setting button through Accessibility, type-select "User
Channel Strip Settings", Right arrow, "Performance", Right arrow, the
preset's name, Return. Before each typed step the script counts Logic's
open menus on screen (``scripts/menu_open.js``), because letters typed with
no menu open would fire Logic's key commands; a wrong count closes the menus
and stops with nothing chosen. Proven live 2026-10-28.
"""

from __future__ import annotations

import difflib
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from hiremarco import config

SCRIPTS = Path(__file__).parent / "scripts"
DEFAULT_DIR = Path.home() / "Music" / "Audio Music Apps" / "Channel Strip Settings" / "Track" / "Performance"


class PresetError(RuntimeError):
    pass


def preset_dir() -> Path:
    return Path(config.get("HIREMARCO_PRESET_DIR") or DEFAULT_DIR)


def list_presets(folder: Path | None = None) -> list[str]:
    folder = folder or preset_dir()
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.glob("*.cst"))


def _words(name: str) -> str:
    name = re.sub(r"^\d{3}-", "", name.lower())
    name = re.sub(r"\b(preset|chain setting|setting|my|the|use|load|give me|put on)\b", " ", name)
    return " ".join(re.sub(r"[^a-z0-9' ]", " ", name).split())


def match(spoken: str, names: list[str]) -> str | None:
    """The one preset the words name, or None. 'my chain' -> '002-MY CHAIN!'."""
    said = _words(spoken)
    if not said:
        return None
    number = re.search(r"\b(\d{1,3})\b", spoken)
    by_words = {n: _words(n) for n in names}
    exact = [n for n, w in by_words.items() if w == said]
    if len(exact) == 1:
        return exact[0]
    if number:
        numbered = [n for n in names if n[:3].isdigit() and int(n[:3]) == int(number.group(1))]
        if len(numbered) == 1:
            return numbered[0]
    # "my chain" also matches "MY CHAIN!" once filler words go; close spellings from speech
    scored = sorted(((difflib.SequenceMatcher(None, said, w).ratio(), n) for n, w in by_words.items()), reverse=True)
    if scored and scored[0][0] >= 0.8 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.1):
        return scored[0][1]
    return None


def _osascript(args: list[str]) -> str:
    done = subprocess.run(["osascript", *args], capture_output=True, text=True, timeout=30)
    if done.returncode != 0:
        raise PresetError(f"osascript exit {done.returncode}: {done.stderr.strip()[-160:]}")
    return done.stdout.strip()


def load(name: str, *, run: Callable[[list[str]], str] = _osascript) -> str:
    """Load one Performance on Logic's selected track. Returns the script's report."""
    report = run([str(SCRIPTS / "load_preset.applescript"), str(SCRIPTS / "menu_open.js"), name])
    if "stopped:" in report:
        raise PresetError(report.splitlines()[-1])
    return report
