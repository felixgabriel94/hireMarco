"""The song's structure and Felix's bookmarks in Logic: two kinds of marker, kept apart.

Owner 2026-10-31: arrangement markers are the structure (Intro, Verse, Chorus, Bridge, Outro), and Marco works on
whole sections with them ("copy chorus 1 into chorus 2" brings every region under it); regular markers are notes
and bookmarks ("mark this, I want to come back to it").

Logic shows arrangement markers to no program: they are not in the Marker List, not in the accessibility tree
(checked live 2026-10-31). The Marker track's own menu bridges them: "Create from Arrangement Markers" puts the
structure in the Marker List, where Marco reads it and then takes those markers away again, and "Convert to
Arrangement Markers" turns markers he lays at exact bars into sections. His bookmarks are set aside while a layout is
built and put back after it. That menu opens only on a real click. A section is copied by setting the locators around
it, selecting everything inside them, copying, and pasting at the target section's first bar. No marker set is made
or deleted: deleting one by Accessibility crashed Logic (live 2026-10-31).
"""

from __future__ import annotations

import re
import subprocess
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

SCRIPT = Path(__file__).parent / "scripts" / "markers_io.applescript"
NAMES = ("Intro", "Verse", "Pre-Chorus", "Chorus", "Post-Chorus", "Hook", "Bridge", "Breakdown", "Interlude",
         "Drop", "Solo", "Outro")
ORDINAL = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "last": -1}
# the Marker track's menu, top to bottom after "Marker Sets": how many arrow presses reach each item (live 2026-10-31)
MENU = {"from_arrangement": 3, "to_arrangement": 4}
KEYS = {
    "select_inside_locators": ("l", ("shift",)),  # Select All Inside Locators, Logic's default Shift-L
    "copy": ("c", ("command",)),
    "paste": ("v", ("command",)),
}


@dataclass(frozen=True)
class Section:
    name: str
    bar: int
    bars: int = 0  # 0: runs to the end

    @property
    def end(self) -> int:
        return self.bar + self.bars if self.bars else 0


@dataclass(frozen=True)
class Mark:
    name: str
    bar: int
    beat: int = 1


def section_name(word: str) -> str:
    """A spoken section name as Logic writes it: "pre chorus" is "Pre-Chorus", "hook" is "Hook"."""
    key = re.sub(r"[\s_-]+", "", word.lower())
    for name in NAMES:
        if re.sub(r"-", "", name.lower()) == key:
            return name
    return " ".join(w.capitalize() for w in word.split())


def parse_layout(text: str) -> list[tuple[str, int]]:
    """"intro 4 bars, verse 8, chorus 8, verse 8, chorus 8, bridge 4, outro 4" as (name, bars) in order."""
    pairs = re.findall(r"([A-Za-z][A-Za-z\s-]*?)\s*(?:for\s+)?(\d+)(?:\s*bars?)?(?=\s*(?:,|;|then|and|\.|$))", text,
                       re.I)
    out = []
    for name, bars in pairs:
        name = re.sub(r"^(?:then|and|a|an|the)\s+", "", name.strip(), flags=re.I).strip()
        if name and int(bars) > 0:
            out.append((section_name(name), int(bars)))
    return out


def layout(pairs: list[tuple[str, int]], start: int = 1) -> list[Section]:
    sections, bar = [], max(1, start)
    for name, bars in pairs:
        sections.append(Section(name, bar, bars))
        bar += bars
    return sections


def find(sections: list[Section], said: str) -> Section | None:
    """"chorus 2", "the second chorus", "last verse", "bridge": Logic does not number repeats, so they are counted in
    order; a bare name is the first of its kind."""
    said = " ".join(said.lower().replace("#", " ").split())
    n = 1
    m = re.match(r"(?:the\s+)?(first|second|third|fourth|fifth|last)\s+(.+)", said)
    if m:
        n, said = ORDINAL[m.group(1)], m.group(2)
    m = re.match(r"(.+?)\s*(\d+)$", said)
    if m:
        said, n = m.group(1), int(m.group(2))
    said = re.sub(r"^the\s+", "", said)
    kind = section_name(said).lower()
    matches = [s for s in sections if s.name.lower() == kind]
    if not matches:
        return None
    if n == -1:
        return matches[-1]
    return matches[n - 1] if 0 < n <= len(matches) else None


def labelled(sections: list[Section]) -> list[str]:
    """Each section as he would say it: "Chorus 2: bars 21 to 28"."""
    counts: dict[str, int] = {}
    total = {s.name: sum(1 for t in sections if t.name == s.name) for s in sections}
    out = []
    for s in sections:
        counts[s.name] = counts.get(s.name, 0) + 1
        label = f"{s.name} {counts[s.name]}" if total[s.name] > 1 else s.name
        span = f"bars {s.bar} to {s.end - 1}" if s.bars else f"from bar {s.bar}"
        out.append(f"{label}: {span}")
    return out


def parse_rows(text: str) -> list[tuple[Mark, int]]:
    """The Marker List's rows ("2 1 1 1<TAB>Chorus<TAB>8 0 0 0") as (mark, length in bars; 0 for open-ended)."""
    out = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        pos, name, length = parts[0].split(), parts[1].strip(), parts[2].split()
        if len(pos) < 2 or not pos[0].isdigit():
            continue
        bars = int(length[0]) if length and length[0].isdigit() else 0
        out.append((Mark(name, int(pos[0]), int(pos[1]) if pos[1].isdigit() else 1), bars))
    return out


def _osa(args: list[str]) -> str:
    done = subprocess.run(["osascript", str(SCRIPT), *args], capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[-200:] or f"osascript exit {done.returncode}")
    return done.stdout.strip()


def _front() -> str:
    return subprocess.run(["osascript", "-e", 'tell application "System Events" to get name of first process whose '
                           'frontmost is true'], capture_output=True, text=True, timeout=10).stdout.strip()


def _double_click(x: float, y: float) -> None:
    import Quartz

    def post(kind, clicks=1):
        e = Quartz.CGEventCreateMouseEvent(None, kind, (x, y), Quartz.kCGMouseButtonLeft)
        Quartz.CGEventSetIntegerValueField(e, Quartz.kCGMouseEventClickState, clicks)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, e)

    post(Quartz.kCGEventMouseMoved)
    time.sleep(0.05)
    for clicks in (1, 2):
        post(Quartz.kCGEventLeftMouseDown, clicks)
        time.sleep(0.03)
        post(Quartz.kCGEventLeftMouseUp, clicks)
        time.sleep(0.05)


def _length(bar: str, bars: str) -> str:
    """A marker's length in bars: its ∞ in the Marker List double-clicked and the bars typed (the Owner's tip,
    2026-10-31; live the same night: 6 typed read back "6 0 0 0")."""
    x, y = (float(v) for v in _osa(["lencell", bar]).split(","))
    subprocess.run(["osascript", "-e", 'tell application "Logic Pro" to activate'], check=False, timeout=10)
    time.sleep(0.3)
    if _front() != "Logic Pro":
        raise RuntimeError("Logic is not in front; the length was not typed")
    _double_click(x, y)
    time.sleep(0.8)
    subprocess.run(["osascript", "-e", f'tell application "System Events"\nkeystroke "{int(bars)}"\ndelay 0.1\n'
                    'key code 36\nend tell'], check=True, capture_output=True, timeout=10)
    time.sleep(0.3)
    _osa(["hide"])
    return "length set"


def _run(args: list[str]) -> str:
    """The marker script; "mark" is two steps, the field opened there and the name pasted from here, and "length"
    is a double-click and typed bars."""
    if args[0] == "length":
        return _length(args[1], args[2])
    if args[0] != "mark":
        return _osa(args)
    subprocess.run(["pbcopy"], input=args[1].encode(), check=True, timeout=10)  # before the field opens
    _osa(["markstart"])
    time.sleep(1.5)  # the rename field takes the keys only after this long (live 2026-10-31)
    front = _front()
    if front != "Logic Pro":
        raise RuntimeError(f"Logic is not in front ({front or 'nothing'}); the marker keeps its default name")
    subprocess.run(["osascript", "-e", 'tell application "System Events"\nkeystroke "v" using {command down}\n'
                    'delay 0.2\nkey code 36\nend tell'], check=True, capture_output=True, timeout=15)
    return "marked"


class Arranger:
    """Reads and builds the structure, copies sections, drops and finds bookmarks. ``run`` speaks to the marker
    script; ``menu(item)`` picks an item of the Marker track's menu; ``press(name)`` runs one of KEYS in Logic;
    ``go(bar, beat)`` moves the playhead; ``locators(start, end)`` sets the cycle."""

    def __init__(self, *, run: Callable[[list[str]], str] = _run, menu: Callable[[str], None],
                 press: Callable[[str], None], go: Callable[..., None], locators: Callable[[int, int], None],
                 sleep: Callable[[float], None] = time.sleep):
        self.run, self.menu, self.press, self.go, self.locators, self.sleep = run, menu, press, go, locators, sleep

    def _rows(self) -> list[tuple[Mark, int]]:
        return parse_rows(self.run(["rows"]))

    def _restore(self, before: list[tuple[Mark, int]]) -> None:
        """The Marker List back to ``before``: emptied when it was empty, else the last step undone; checked."""
        if before:
            self.run(["undo"])
        else:
            self.run(["clear"])
        self.sleep(0.3)
        if Counter(self._rows()) != Counter(before):
            raise RuntimeError("the markers did not go back to how they were; check the Marker List")

    def structure(self) -> list[Section]:
        """The arrangement as it is in Logic now: copied into the markers, read, and taken back out."""
        before = self._rows()
        self.menu("from_arrangement")
        self.sleep(0.6)
        added = Counter(self._rows()) - Counter(before)
        if added:
            self._restore(before)
        return sorted((Section(m.name, m.bar, bars) for m, bars in added.elements()), key=lambda s: s.bar)

    def build(self, sections: list[Section]) -> list[Section]:
        """His bookmarks set aside, a marker at each section's first bar, converted into arrangement markers, the
        bookmarks put back; the read-back is the result, never the plan."""
        bookmarks = [m for m, _ in self._rows()]
        if bookmarks:
            self.run(["clear"])
        for s in sections:
            self.go(s.bar)
            self.run(["mark", s.name])
        for s in sections:  # each marker's own length, or the last section takes Logic's default
            if s.bars:
                self.run(["length", str(s.bar), str(s.bars)])
        self.menu("to_arrangement")
        self.sleep(0.6)
        if self._rows():  # whatever the conversion left behind as plain markers
            self.run(["clear"])
        for m in bookmarks:
            self.go(m.bar, m.beat)
            self.run(["mark", m.name])
        return self.structure()

    def copy_section(self, sections: list[Section], source: str, target: str) -> str:
        src, dst = find(sections, source), find(sections, target)
        if src is None or dst is None:
            missing = source if src is None else target
            return f"no section called {missing!r} in this song"
        if not src.bars:
            return f"{source} has no end, so there is nothing to measure the copy by"
        self.locators(src.bar, src.end)
        self.press("select_inside_locators")
        self.press("copy")
        self.go(dst.bar)
        self.press("paste")
        return f"copied {source} (bars {src.bar} to {src.end - 1}) to bar {dst.bar}"

    def bookmark(self, name: str) -> str:
        """A regular marker at the playhead, named: a note on the timeline, never a section."""
        self.run(["mark", name])
        return f"marked {name}"

    def bookmarks(self) -> list[Mark]:
        return [m for m, _ in self._rows()]

    def find_bookmark(self, said: str) -> Mark | None:
        """The bookmark whose name shares the most words with what he said; the newest one when he names none."""
        marks = self.bookmarks()
        if not marks:
            return None
        words = set(re.findall(r"\w+", said.lower())) - {"the", "a", "that", "to", "back", "go", "take", "me", "marker"}
        if not words:
            return marks[-1]
        scored = max(marks, key=lambda m: len(words & set(re.findall(r"\w+", m.name.lower()))))
        return scored if words & set(re.findall(r"\w+", scored.name.lower())) else None


def live_arranger(conn=None, rules_path: Path | None = None) -> Arranger:
    """The booth's arranger: key presses and clicks go to Logic with Logic in front, each through the gate as a Logic
    action."""
    import uuid

    from hiremarco import gate
    from hiremarco.studio.logic import KEYMAP, TENANT, Press, _osascript, _script

    def gated(run: Callable[[], None], what: str) -> None:
        gate.execute_effect(conn or gate.connect(), lambda: run() or what, tenant_id=TENANT,
                            idempotency_key=f"logic:{uuid.uuid4()}", capability="arrange", channel="logic",
                            target="*", message=what, department="studio", rules_path=rules_path)

    def key(press: Press) -> None:
        _osascript(_script(press))
        time.sleep(0.15)

    def front() -> None:
        subprocess.run(["osascript", "-e", 'tell application "Logic Pro" to activate'], check=False, timeout=10)
        time.sleep(0.3)
        name = subprocess.run(["osascript", "-e", 'tell application "System Events" to get name of first process '
                               'whose frontmost is true'], capture_output=True, text=True, timeout=10).stdout.strip()
        if name != "Logic Pro":
            raise RuntimeError(f"Logic is not in front ({name or 'nothing'}); nothing was clicked")

    def menu(item: str) -> None:
        def run() -> None:
            import Quartz

            _run(["hide"])  # the Marker List floats over the Marker track's name (live 2026-10-31)
            front()
            x, y = (float(v) for v in _run(["header"]).split(","))
            for kind in (Quartz.kCGEventMouseMoved, Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
                Quartz.CGEventPost(Quartz.kCGHIDEventTap,
                                   Quartz.CGEventCreateMouseEvent(None, kind, (x, y), Quartz.kCGMouseButtonLeft))
                time.sleep(0.08)
            time.sleep(0.6)  # the menu is open now and holds Logic: no front() here, it would hang (live 2026-10-31)
            downs = "\n".join(["key code 125", "delay 0.15"] * MENU[item])
            subprocess.run(["osascript", "-e", f'tell application "System Events"\n{downs}\nkey code 36\nend tell'],
                           check=True, capture_output=True, timeout=15)
        gated(run, item.replace("_", " "))

    def press(name: str) -> None:
        letter, mods = KEYS[name]
        gated(lambda: key(Press(letter, mods)), name.replace("_", " "))

    def go(bar: int, beat: int = 1) -> None:
        # the playhead's bar in the Control Bar, set without keys: typed digits and spaces reached the transport and
        # started playback (live 2026-10-31)
        gated(lambda: _run(["goto", str(bar)]), f"go to bar {bar}")

    def locators(start: int, end: int) -> None:
        def run() -> None:
            for bar, which in ((start, "set_left_locator"), (end, "set_right_locator")):
                _run(["goto", str(bar)])
                key(Press(*KEYMAP[which]))
        gated(run, f"locators {start} to {end}")

    return Arranger(menu=menu, press=press, go=go, locators=locators)
