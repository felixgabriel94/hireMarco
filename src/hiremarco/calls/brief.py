"""The call brief: everything the other side will predictably ask, settled before Marco dials.

Owner 2026-10-31: Marco goes into every call fully briefed instead of saying he
will check with Felix. Each kind of call lists the fields it needs. The
standing facts about Felix (name, email, usual preferences) live in a profile
outside the repository, ``~/.config/hiremarco/profile.json`` beside the env
file; the rest comes from ``--brief KEY=VALUE`` or a brief file. A call with a
needed field still empty is refused before dialing, naming the fields, so the
question goes to Felix first and never comes up mid-call.
"""

from __future__ import annotations

import json
from pathlib import Path

from hiremarco import config


class BriefIncomplete(ValueError):
    def __init__(self, kind: str, missing: list[str]):
        super().__init__(f"the {kind} brief is missing: {', '.join(missing)}")
        self.kind, self.missing = kind, missing


# What the other side predictably asks, per kind of call, in the order Marco would be asked.
NEEDS = {
    "reservation": ["name", "party_size", "date", "time", "time_window", "seating", "occasion",
                    "special_requests", "callback", "email", "card_hold"],
    "generic": ["name", "callback", "email", "ask", "if_unavailable"],
}
LABELS = {
    "name": "name on the booking (first and last)", "party_size": "party size", "date": "date", "time": "time",
    "time_window": "acceptable window around that time", "seating": "seating (indoor, outdoor, any)",
    "occasion": "occasion", "special_requests": "special requests or allergies",
    "callback": "callback number", "email": "email for the confirmation", "card_hold": "if they need a card",
    "ask": "what to ask or arrange", "if_unavailable": "if it cannot be done",
}
# Fixed, not asked: he never reads out a card, and the line he calls from is the callback unless told otherwise.
FIXED = {
    "card_hold": "Felix completes any card hold himself, by a link or a callback; never read out card details",
    "callback": "this number, the line Marco is calling from",
}
# say_as: how a word is said aloud on a call, "Word=Respelling; Other=Respelling" (the relay swaps it in speech only)
PROFILE_FIELDS = {"full_name": "", "email": "", "seating": "", "special_requests": "", "time_window": "", "say_as": ""}


def say_as(profile: dict[str, str] | None = None) -> dict[str, str]:
    """The profile's respellings, word to how it is said; letter-by-letter spelling is left alone."""
    profile = load_profile() if profile is None else profile
    pairs = {}
    for item in (profile.get("say_as") or "").split(";"):
        word, sep, spoken = item.partition("=")
        if sep and word.strip() and spoken.strip():
            pairs[word.strip()] = spoken.strip()
    return pairs


def profile_path() -> Path:
    return config.env_path().parent / "profile.json"


def load_profile(path: Path | None = None) -> dict[str, str]:
    path = path or profile_path()
    if not path.exists():
        return dict(PROFILE_FIELDS)
    return {**PROFILE_FIELDS, **{k: str(v) for k, v in json.loads(path.read_text()).items()}}


def save_profile(values: dict[str, str], path: Path | None = None) -> Path:
    path = path or profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, indent=2, ensure_ascii=False) + "\n")
    path.chmod(0o600)
    return path


def kind_for(purpose: str) -> str:
    """A restaurant reservation only by its own words; "booking a studio session" is a generic call (2026-10-31)."""
    words = purpose.lower()
    return "reservation" if any(w in words for w in ("table", "reserv", "dinner", "lunch", "restaurant")) else "generic"


def parse_pairs(pairs: list[str]) -> dict[str, str]:
    out = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise ValueError(f"--brief takes KEY=VALUE, not {pair!r}")
        out[key.strip()] = " ".join(value.split())
    return out


def build(kind: str, given: dict[str, str], profile: dict[str, str] | None = None) -> dict[str, str]:
    """The brief for this kind of call: fixed lines, then the profile, then what was given. Raises when incomplete."""
    if kind not in NEEDS:
        raise ValueError(f"no brief kind {kind!r}; one of {', '.join(NEEDS)}")
    profile = load_profile() if profile is None else profile
    standing = {"name": profile.get("full_name", ""), "email": profile.get("email", ""),
                "seating": profile.get("seating", ""), "special_requests": profile.get("special_requests", ""),
                "time_window": profile.get("time_window", "")}
    merged = {**FIXED, **{k: v for k, v in standing.items() if v}, **{k: v for k, v in given.items() if v}}
    missing = [k for k in NEEDS[kind] if not merged.get(k, "").strip()]
    if missing:
        raise BriefIncomplete(kind, missing)
    return {k: merged[k] for k in NEEDS[kind]} | {k: v for k, v in given.items() if k not in NEEDS[kind]}


def render(brief: dict[str, str]) -> str:
    return "\n".join(f"- {LABELS.get(k, k.replace('_', ' '))}: {v}" for k, v in brief.items())


def unspell(text: str, profile: dict[str, str] | None = None) -> str:
    """Written text in the real spelling: a respelling made for speech ("Bettencourt") back to its word
    ("Betancourt"). Everything shown or logged goes through this; only speech uses the respelling (Owner 2026-10-31)."""
    import re

    for word, spoken in say_as(profile).items():
        text = re.sub(rf"\b{re.escape(spoken)}\b", word, text or "")
    return text or ""
