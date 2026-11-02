"""Roles, not plugin names: what a mastering chain is made of, and what fills each role here.

Owner 2026-11-02: like a great engineer, Marco works with what is in the
room. The chain is written as roles in the order the rulebook gives; each
role lists the plugins that can fill it, best first, as Logic names them in
its insert menu, and ends with Logic's own plugin so an artist with stock
plugins gets the same chain. What the artist owns comes from the license
ledger and Logic's plug-in list (``studio.ledger``), never from a guess: a
plugin that is not in the room is never named in a plan.
"""

from __future__ import annotations

import json
from pathlib import Path

from hiremarco import config

MAPS = Path(config.STATE_DIR) / "maps"   # logic_plugins.json and license_ledger.json, written by `marco ledger build`

ORDER = ("gain", "corrective_eq", "dynamics", "glue", "tonal_eq", "color", "width", "limiter", "meter")

# Best first, Logic's own plugin last. Names as Logic's insert menu shows them (logic_plugins.json, read 2026-11-02).
CANDIDATES: dict[str, list[str]] = {
    "gain": ["Gain"],
    "corrective_eq": ["Pro-Q 3", "TBTECH Kirchhoff-EQ", "UAD Oxford EQ", "Ozone 11 Dynamic EQ", "Linear Phase EQ",
                      "Channel EQ"],
    "dynamics": ["Pro-MB", "Ozone 11 Dynamics", "UAD Oxford Dynamic EQ", "Ozone 11 Dynamic EQ", "Multipressor"],
    "glue": ["Shadow Hills Mastering Compress", "UAD Shadow Hills Mastering Comp", "AMEK Mastering Compressor",
             "UAD elysia alpha master", "UAD Manley Variable Mu", "UAD API 2500", "SSL Native Bus Compressor 2",
             "Ozone 11 Vintage Compressor", "Compressor"],
    # native plug-ins before the UAD DSP ones: a DSP plug-in on the Stereo Out prints only in real time (2026-11-02)
    "tonal_eq": ["AMEK EQ 250", "Pro-Q 3", "Ozone 11 Vintage EQ", "UAD Manley Massive Passive MST", "UAD Pultec EQP-1A",
                 "Vintage Tube EQ", "Channel EQ"],
    "color": ["Kiive Tape Face", "UAD Ampex ATR-102", "Black Box Analog Design HG-2MS", "Saturn 2",
              "SSL Fusion Vintage Drive", "Ozone 11 Vintage Tape", "UAD Oxford Inflator", "Phat FX"],
    "width": ["Ozone 11 Imager", "SSL Fusion Stereo Image", "Black Box Analog Design HG-2MS", "Stereo Spread",
              "Direction Mixer"],
    "limiter": ["Pro-L 2", "UAD Oxford Limiter", "Ozone 11 Maximizer", "bx_limiter True Peak", "SSL X-Limit",
                "UAD Precision Limiter", "Adaptive Limiter", "Limiter"],
    "meter": ["Tonal Balance Control 2", "SSL Meter", "Loudness Meter", "MultiMeter", "Correlation Meter"],
}
# A whole bus chain in one plugin, Joshua's way, offered beside the roles when the artist owns one.
WHOLE_CHAIN = ["The God Particle", "Ozone 11"]
STOCK = {"Gain", "Linear Phase EQ", "Channel EQ", "Multipressor", "Compressor", "Vintage Tube EQ", "Phat FX",
         "Stereo Spread", "Direction Mixer", "Adaptive Limiter", "Limiter", "Loudness Meter", "MultiMeter",
         "Correlation Meter", "Match EQ", "Exciter"}
# The roles a quick master uses, and the roles only a named problem adds (rulebook: dynamics, width, color are
# for a named problem or a wanting genre, never the default).
DEFAULT_ROLES = ("gain", "corrective_eq", "glue", "tonal_eq", "limiter", "meter")
ON_DEMAND = ("dynamics", "color", "width")


def _strip(name: str) -> str:
    return name[:-6] if name.endswith(" (s/s)") else name


def in_the_room(maps: Path = MAPS) -> set[str]:
    """Every plugin Logic lists on this Mac, minus what the license ledger says is not owned."""
    maps = Path(maps)
    listed = maps / "logic_plugins.json"
    names = {_strip(n) for n in json.loads(listed.read_text())} if listed.exists() else set()
    ledger = maps / "license_ledger.json"
    if ledger.exists():
        for name, row in json.loads(ledger.read_text()).items():
            # not_owned: never licensed; inactive: a subscription that lapsed (Plugin Alliance, Owner 2026-11-02),
            # which loads, shows "subscription not active" and passes silence
            if row.get("status") in ("not_owned", "inactive"):
                names.discard(_strip(name))
    return names


def fill(role: str, room: set[str], *, stock_only: bool = False) -> str | None:
    """The best plugin in the room for the role, or the stock one when asked; None when the room has nothing."""
    for name in CANDIDATES[role]:
        if stock_only and name not in STOCK:
            continue
        if name in room:
            return name
    return None


def chain(room: set[str], *, roles: tuple[str, ...] = DEFAULT_ROLES, stock_only: bool = False) -> dict[str, str]:
    """Role to plugin, in the rulebook's order, skipping a role nothing in the room can fill."""
    out = {}
    for role in ORDER:
        if role not in roles:
            continue
        name = fill(role, room, stock_only=stock_only)
        if name:
            out[role] = name
    return out


def for_model(room: set[str]) -> dict:
    """What the planner may name: per role, the candidates in the room, best first; whole-chain plugins apart."""
    return {"roles_in_order": list(ORDER),
            "candidates": {role: [n for n in names if n in room] for role, names in CANDIDATES.items()},
            "stock_fallbacks": {role: fill(role, room, stock_only=True) for role in ORDER},
            "whole_chain": [n for n in WHOLE_CHAIN if n in room],
            "default_roles": list(DEFAULT_ROLES), "on_demand_roles": list(ON_DEMAND)}
