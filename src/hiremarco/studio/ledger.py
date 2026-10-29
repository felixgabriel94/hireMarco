"""The license ledger: which plug-ins this artist owns, and how Marco knows.

Ownership is read from evidence already on the Mac, never asked one plug-in at
a time, and never from a secret: no serial, key or password is copied here,
only product names and where the evidence came from.

Evidence, strongest first:

- ``logic``: one of Logic's own plug-ins, which come with Logic;
- ``console``: UAD Console says the plug-in is authorized, or in a demo with
  days left (exact, from the vendor's own engine);
- ``used``: the plug-in appears in the artist's saved channel strips, patches,
  plug-in presets or Logic projects (if it was used, it opened);
- ``registered``: a Native Instruments product record carries a registration;
- ``installed``: a vendor folder exists for it (weak: installers drop folders
  for products not bought).

A plug-in with only weak evidence is ``unknown`` until Marco tries it on a
scratch track. ``not_owned`` comes from Console (UAD, not authorized) or from
the artist's own do-not-use list (a trial that ended).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

LOGIC_LIBRARY = Path.home() / "Music" / "Audio Music Apps"
PROJECT_FOLDERS = (Path.home() / "Music" / "Logic",)
NI_RECORDS = Path("/Library/Application Support/Native Instruments/Service Center")
VENDOR_FOLDERS = (Path.home() / "Library/Application Support/FabFilter", Path("/Library/Application Support/Slate Digital"),
                  Path("/Library/Application Support/Plugin Alliance"))


def base_name(logic_name: str) -> str:
    """'CLA-76 (s) (s/s)' -> 'CLA-76'; 'UAD Neve 1073 (s/s)' -> 'UAD Neve 1073'."""
    name = logic_name
    while name.endswith(")") and " (" in name:
        name = name.rsplit(" (", 1)[0]
    return name.strip()


def strings_in(paths: Iterable[Path], wanted: set[str], max_bytes: int = 64 << 20) -> set[str]:
    """Which of the wanted names occur as text inside these files (channel strips and projects are binary,
    but plug-in names are stored as plain strings)."""
    found: set[str] = set()
    encoded = {name: name.encode() for name in wanted}
    for path in paths:
        try:
            if path.stat().st_size > max_bytes:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        found |= {name for name, raw in encoded.items() if name not in found and raw in data}
    return found


def used_files(library: Path = LOGIC_LIBRARY, projects: Iterable[Path] = PROJECT_FOLDERS) -> list[Path]:
    files = []
    for sub in ("Channel Strip Settings", "Patches"):
        folder = library / sub
        if folder.is_dir():
            files += [p for p in folder.rglob("*") if p.is_file() and p.suffix in (".cst", ".patch", ".pst")]
    for folder in projects:
        if folder.is_dir():
            files += list(folder.rglob("ProjectData"))
    return files


def preset_folders(library: Path = LOGIC_LIBRARY) -> set[str]:
    folder = library / "Plug-In Settings"
    return {p.name for p in folder.iterdir() if p.is_dir()} if folder.is_dir() else set()


def registered_ni(records: Path = NI_RECORDS) -> set[str]:
    """Native Instruments products whose record holds a registration (the value itself is not kept)."""
    names = set()
    if records.is_dir():
        for path in records.glob("*.xml"):
            text = path.read_text(errors="ignore")
            if re.search(r"<RegKey>\s*[^<\s]", text):
                match = re.search(r"<Name>([^<]+)</Name>", text)
                names.add(match.group(1).strip() if match else path.stem)
    return names


def installed(folders: Iterable[Path] = VENDOR_FOLDERS) -> set[str]:
    return {p.name for folder in folders if folder.is_dir() for p in folder.iterdir() if p.is_dir()}


def built_in(logic_names: list[str]) -> set[str]:
    """Logic's own plug-ins: Logic lists them first, before any Audio Unit (live order 2026-10-29: 126 of
    Apple's, ChromaGlow last, then the UAD titles). The run ends at the first third-party name."""
    first_au = next((i for i, n in enumerate(logic_names) if n.startswith("UAD ")), 0)
    return set(logic_names[:first_au])


def build(logic_names: list[str], uad_ok: set[str], uad_all: set[str], not_owned: set[str],
          used: set[str], presets: set[str], registered: set[str], present: set[str]) -> dict[str, dict]:
    """One row per plug-in Logic lists: status and the evidence behind it."""
    rows = {}
    apple = built_in(logic_names)
    for logic_name in logic_names:
        name = base_name(logic_name)
        evidence = ["logic"] if logic_name in apple else []
        if name in uad_ok:
            evidence.append("console")
        if name in used or name in presets:
            evidence.append("used")
        if any(name == r or name.startswith(r + " ") for r in registered):
            evidence.append("registered")
        if any(name == p or name.startswith(p + " ") or p.startswith(name + " ") for p in present):
            evidence.append("installed")
        if name in not_owned or (name.startswith("UAD ") and name in uad_all and name not in uad_ok):
            status = "not_owned"
        elif set(evidence) & {"logic", "console", "used", "registered"}:
            status = "owned"
        else:
            status = "unknown"
        rows[logic_name] = {"status": status, "evidence": evidence}
    return rows


def read_ledger(path: Path) -> dict[str, dict]:
    return json.loads(path.read_text()) if path.exists() else {}


def mark(path: Path, logic_name: str, status: str, why: str) -> None:
    """Record what a scratch-track test found ("owned" or "not_owned") so it is never tested again."""
    rows = read_ledger(path)
    row = rows.setdefault(logic_name, {"status": "unknown", "evidence": []})
    row["status"] = status
    row["evidence"] = sorted(set(row["evidence"]) | {why})
    path.write_text(json.dumps(rows, indent=1))
