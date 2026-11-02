"""The UAD Control Panel's Plug-Ins tab, read the way the vendor shows it.

UA's engine answers over TCP with one Status text per plug-in ("Authorized
for all devices", "Demo not started", "Demo (14 days left)"); the UAD Control
Panel draws the same list with its buttons (START DEMO, BUY) and the account's
live demo count. The panel's table has no accessibility tree (zero children,
live 2026-11-02), so it is read the way an engineer reads it: the window
captured page by page, the text recognized on this Mac by Apple's Vision
framework (no model call, 0.6 s a page), every row matched to UA's own list
file (Powered Plugins.ini) so a fused or split name lands on its title.

The engine is what Logic's UAD plug-ins run on, so the engine decides what is
in the room; the panel can only take a plug-in out. A demo the panel shows but
the engine has not loaded (no new authorization file yet) stays out until the
Owner presses "Authorize Plug-Ins..." in the panel, and a START DEMO against an
engine that says authorized stays out until its face is read on the strip.
"""

from __future__ import annotations

import datetime as dt
import difflib
import json
import re
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

APP = "UAD Meter & Control Panel"
WINDOW = "UAD Control Panel"
INI = Path.home() / "Library/Preferences/Universal Audio/Powered Plugins.ini"
OCR = Path(__file__).with_name("scripts") / "uad_ocr.js"
NAME_X, STATUS_X = 500, 850   # capture pixels at 2x, no shadow: the name column ends, the status column ends
HEADER_Y = 300                # the table header sits above this line
ROW_TOLERANCE = 12            # texts within this many pixels of each other are one row
PAGE_UNITS = 12               # wheel units per page down (about 15 rows of 22 visible)
TOP_UNITS = 400               # enough to reach the top from anywhere
MAX_PAGES = 60
STOP_WORDS = {"uad", "collection", "plugin", "plugins", "the", "and", "of"}


def plain(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def kind_of(status: str) -> tuple[str, int | None]:
    """The ledger status a shown Status text means, and the demo days left when it is a demo. Tolerant of a
    half-recognized word: "Autharizad for all davicnd" is still an authorization."""
    s = status.strip().lower()
    if s.startswith("auth"):
        return "owned", None
    m = re.match(r"demo \((\d+) days? left\)", s)
    if m:
        return "demo", int(m.group(1))
    if s.startswith(("start demo", "demo not started", "demo expired")):
        return "not_owned", None
    if s.startswith("update"):
        return "inactive", None   # the plug-in needs newer UAD software before it loads
    return "unknown", None


def ini_titles(path: Path = INI) -> list[str]:
    return [p.get("title", "") for p in ET.parse(path).getroot().iter("plugin")]


def tokens(name: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", name.lower()) if w not in STOP_WORDS}


def _covers(a: set[str], b: set[str]) -> bool:
    """Every token of a has a token of b that starts it or that it starts: comp ~ compressor, mic ~ microphone."""
    return all(any(x == y or x.startswith(y) or y.startswith(x) for y in b) for x in a)


def match_title(name: str, titles: list[str]) -> str | None:
    """The panel title for an engine plug-in name: the same words, allowing UA's longer form on either side
    ("UAD Hitsville EQ" is a row of "UAD Hitsville EQ Collection"; "UAD Manley Reference Mic Preamp" is
    "UAD Manley Reference Microphone Preamplifier"); the closest in length wins; none when nothing covers."""
    key = plain(name.removeprefix("UAD "))
    exact = [t for t in titles if plain(t.removeprefix("UAD ")) == key]
    if exact:
        return exact[0]
    mine = tokens(name)
    best = None
    for title in titles:
        theirs = tokens(title)
        if mine and theirs and (_covers(mine, theirs) or _covers(theirs, mine)):
            score = abs(len(theirs) - len(mine))
            if best is None or score < best[0]:
                best = (score, title)
    return best[1] if best else None


def title_of(name: str, by_plain: dict[str, str]) -> str:
    """A recognized name on its UA title: exact, else the closest spelling, else kept with a question mark."""
    key = plain(name)
    if key in by_plain:
        return by_plain[key]
    close = difflib.get_close_matches(key, list(by_plain), n=1, cutoff=0.85)
    return by_plain[close[0]] if close else f"? {name}"


# the hands
def window() -> tuple[int, float, float, float, float]:
    import Quartz

    for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID):
        if w.get("kCGWindowOwnerName") == APP and w.get("kCGWindowName") == WINDOW:
            b = w["kCGWindowBounds"]
            return int(w["kCGWindowNumber"]), float(b["X"]), float(b["Y"]), float(b["Width"]), float(b["Height"])
    raise RuntimeError(f"the {WINDOW} window is not on screen; open {APP} on its Plug-Ins tab")


def activate() -> None:
    subprocess.run(["osascript", "-e", f'tell application "{APP}" to activate'], check=False, timeout=10)
    time.sleep(0.6)


def capture(wid: int, path: Path) -> Path:
    subprocess.run(["screencapture", "-x", "-o", "-l", str(wid), "-t", "png", str(path)], check=True, timeout=10)
    return path


def recognize(png: Path) -> list[dict]:
    out = subprocess.run(["osascript", "-l", "JavaScript", str(OCR), str(png)], capture_output=True, text=True,
                         timeout=30, check=True)
    return json.loads(out.stdout)["rows"]


def wheel(x: float, y: float, units: int) -> None:
    """A scroll wheel at a screen point: positive units scroll toward the top (live 2026-11-02)."""
    import Quartz

    Quartz.CGEventPost(Quartz.kCGHIDEventTap,
                       Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, (x, y), 0))
    time.sleep(0.05)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap,
                       Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, units))


def table_rows(texts: list[dict]) -> list[tuple[str, str]]:
    """(name, status) per table row: texts grouped by their y, the name left of the status column, the status
    in it, the ? and $ buttons dropped."""
    groups: list[dict] = []
    for t in texts:
        if t["y"] < HEADER_Y or t["text"] in ("?", "$"):
            continue
        for g in groups:
            if abs(g["y"] - t["y"]) <= ROW_TOLERANCE:
                g["items"].append(t)
                break
        else:
            groups.append({"y": t["y"], "items": [t]})
    rows = []
    for g in sorted(groups, key=lambda g: g["y"]):
        names = [i["text"] for i in sorted(g["items"], key=lambda i: i["x"]) if i["x"] < NAME_X]
        stats = [i["text"] for i in g["items"] if NAME_X <= i["x"] < STATUS_X]
        if names:
            rows.append((" ".join(names), stats[0] if stats else ""))
    return rows


def read_panel(*, scratch: Path | None = None, titles: list[str] | None = None, settle: float = 0.6,
               activate: Callable[[], None] = activate, window: Callable = window, capture: Callable = capture,
               recognize: Callable = recognize, wheel: Callable = wheel,
               log: Callable[[str], None] = lambda s: None) -> dict[str, str]:
    """Every row of the Plug-Ins tab, UA's title -> the Status text shown, top to bottom."""
    titles = titles if titles is not None else ini_titles()
    by_plain = {plain(t.removeprefix("UAD ")): t for t in titles}
    activate()
    wid, x, y, w, h = window()
    at = (x + w / 2, y + h * 0.6)
    wheel(*at, TOP_UNITS)
    time.sleep(settle)
    seen: dict[str, str] = {}
    order: list[str] = []
    prev: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for page in range(1, MAX_PAGES + 1):
            png = Path(scratch or tmp) / f"uad_page_{page:02d}.png"
            rows = table_rows(recognize(capture(wid, png)))
            if any(kind_of(s)[0] == "unknown" for _, s in rows):   # a row caught mid-scroll: once more, settled
                time.sleep(settle)
                rows = table_rows(recognize(capture(wid, png)))
            new = 0
            for name, status in rows:
                title = title_of(name, by_plain)
                if title not in seen:
                    seen[title] = status
                    order.append(title)
                    new += 1
                elif status and kind_of(seen[title])[0] == "unknown":
                    seen[title] = status   # the clearer read of the same row
            log(f"   panel page {page}: {len(rows)} rows, {new} new")
            if not new:
                break
            if prev and rows and title_of(rows[0][0], by_plain) not in prev:
                raise RuntimeError("the panel moved more than a page between captures; nothing read past "
                                   f"{prev[-1]!r}")
            prev = [title_of(n, by_plain) for n, _ in rows]
            wheel(*at, -PAGE_UNITS)
            time.sleep(settle)
    return {t: seen[t] for t in order}


def reconcile(engine: dict[str, str], panel: dict[str, str] | None, today: dt.date | None = None) -> dict[str, dict]:
    """One ledger row per engine plug-in: the status and both readings as evidence. The engine decides; a panel
    reading that disagrees takes the plug-in out (not_owned) and says why, since Logic runs what the engine
    has loaded, not what the account shows."""
    panel = panel or {}
    titles = list(panel)
    today = today or dt.date.today()
    rows = {}
    for name, status in engine.items():
        kind, days = kind_of(status)
        evidence = [f"engine: {status}"]
        title = match_title(name, titles) if titles else None
        if title is not None:
            shown = panel[title]
            shown_kind, shown_days = kind_of(shown)
            evidence.append(f"panel: {shown}")
            if shown_kind != kind:
                if shown_kind == "demo" and kind == "not_owned":
                    evidence.append("the panel shows a demo the engine has not loaded: press Authorize Plug-Ins... "
                                    "in the UAD Control Panel, then build the ledger again")
                else:
                    evidence.append("the engine and the panel disagree; out of the room until its face is read")
                kind = "not_owned" if kind != "inactive" else kind
            days = days or shown_days
        if kind == "demo" and days:
            evidence.append(f"demo ends {today + dt.timedelta(days=days):%Y-%m-%d}")
        rows[name] = {"status": kind, "evidence": evidence}
    return rows
