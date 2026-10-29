"""The session view: a Controls view for the whole song, so Marco knows instead of guesses.

Per track he holds his own reading (``ears.TrackReport``: spectrum bands,
loudness, peaks, dynamics, width) and a **role** read from the name and
confirmed by the measurement (a "Kick" with its energy in the mids is flagged).

Between tracks, three readings replace one pile of curves:

1. **The collision grid**: every pair, every band, ranked by the energy
   involved, so an 80-track session (3,160 pairs) comes back as the ten
   fights that matter.
2. **Each track against the rest of the mix**: how much of the track's energy
   sits in bands where the rest of the mix is louder (masking), which is the
   "give it space" decision.
3. **Role targets**: the shape of a clean, balanced mix. Each track's reading
   against its role's target is the baseline; the artist's preferences are
   layered on top of baseline, not instead of it.

The **hardware** in front of Logic (the Owner's 6176 and Manley) is part of
the map with its current settings, and one rule decides where a fix lives:
what is already printed to a recording can only be shaped in Logic; what is
happening live on the way in is a hardware move.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from hiremarco import config
from hiremarco.mix.ears import BANDS, EarsReport, TrackReport

ROLES: list[tuple[str, re.Pattern, str]] = [
    ("kick", re.compile(r"\bkick\b|\bbd\b|\b808\b", re.I), "bass"),
    ("bass", re.compile(r"\bbass\b|\bsub\b", re.I), "bass"),
    ("snare", re.compile(r"\bsnare\b|\bclap\b|\bsd\b", re.I), "mids"),
    ("hats", re.compile(r"\bhat|\bhh\b|\bride\b|\bcymbal|\bshaker|\bperc", re.I), "air"),
    ("drums", re.compile(r"\bdrum|\bbeat\b|\bloop\b", re.I), "bass"),
    ("lead vocal", re.compile(r"\blead\b|\bvox\b|\bvocal|\bvoc\b|\bverse|\bchorus\b|\bhook\b", re.I), "upper mids"),
    ("harmony", re.compile(r"\bharm|\bdouble|\bbgv|\bbacking|\bad[- ]?lib|\bstack", re.I), "upper mids"),
    ("guitar", re.compile(r"\bgtr|\bguitar|\bacoustic|\belectric", re.I), "mids"),
    ("keys", re.compile(r"\bkey|\bpiano|\brhodes|\bsynth|\bpad\b|\borgan|\bstring", re.I), "mids"),
    ("fx", re.compile(r"\bfx\b|\briser|\bimpact|\bsweep|\breverse", re.I), "air"),
]

# Where a clean, balanced mix puts each role, relative to the lead vocal (0 dB) in integrated loudness,
# and the band that should carry most of its energy. Starting points an engineer would recognize, not law.
ROLE_TARGETS: dict[str, dict] = {
    "lead vocal": {"lufs_rel": 0.0, "home": "upper mids", "hi_mono": False},
    "harmony": {"lufs_rel": -6.0, "home": "upper mids", "hi_mono": False},
    "kick": {"lufs_rel": -3.0, "home": "bass", "hi_mono": True},
    "bass": {"lufs_rel": -4.0, "home": "bass", "hi_mono": True},
    "snare": {"lufs_rel": -5.0, "home": "mids", "hi_mono": True},
    "drums": {"lufs_rel": -3.0, "home": "bass", "hi_mono": True},
    "hats": {"lufs_rel": -12.0, "home": "air", "hi_mono": False},
    "guitar": {"lufs_rel": -8.0, "home": "mids", "hi_mono": False},
    "keys": {"lufs_rel": -8.0, "home": "mids", "hi_mono": False},
    "fx": {"lufs_rel": -12.0, "home": "air", "hi_mono": False},
    "other": {"lufs_rel": -8.0, "home": "mids", "hi_mono": False},
}
LEVEL_TOLERANCE_DB = 3.0
MASK_DB = 6.0  # a band is masked when the rest of the mix is this much louder there


@dataclass
class Hardware:
    name: str
    role: str            # "mic preamp", "compressor", "eq"
    settings: dict[str, str] = field(default_factory=dict)
    live: bool = True    # in the signal path while recording; already printed on existing tracks


@dataclass
class TrackView:
    name: str
    role: str
    role_from: str           # "name" or "guess"
    reading: TrackReport
    masked_bands: list[str] = field(default_factory=list)
    against_target: list[str] = field(default_factory=list)

    @property
    def home_band(self) -> str:
        return max(self.reading.bands_db, key=self.reading.bands_db.get) if self.reading.bands_db else ""


@dataclass
class Fight:
    a: str
    b: str
    band: str
    gap_db: float
    energy_db: float     # the louder of the two in that band, absolute; ranks the fight


@dataclass
class SessionView:
    tracks: list[TrackView]
    fights: list[Fight]
    hardware: list[Hardware]
    mix_notes: list[str]

    def as_dict(self) -> dict:
        return {
            "tracks": [{"track": t.name, "role": t.role, "role_from": t.role_from, "lufs": t.reading.lufs,
                        "true_peak_db": t.reading.true_peak_db, "crest_db": t.reading.crest_db,
                        "home_band": t.home_band, "bands_db": t.reading.bands_db,
                        "masked_bands": t.masked_bands, "against_target": t.against_target}
                       for t in self.tracks],
            "fights": [asdict(f) for f in self.fights],
            "hardware": [asdict(h) for h in self.hardware],
            "mix_notes": self.mix_notes,
        }


def role_of(name: str, reading: TrackReport | None = None) -> tuple[str, str]:
    for role, pattern, _ in ROLES:
        if pattern.search(name):
            return role, "name"
    if reading and reading.bands_db:
        home = max(reading.bands_db, key=reading.bands_db.get)
        if home in ("sub", "bass"):
            return "bass", "guess"
        if home == "air":
            return "hats", "guess"
    return "other", "guess"


def band_level(t: TrackReport, band: str) -> float:
    """The track's absolute level in a band: its loudness plus the band's share."""
    return t.lufs + t.bands_db.get(band, -120.0)


def collision_grid(tracks: list[TrackReport], gap_db: float = 6.0, strong_db: float = -12.0, top: int = 10) -> list[Fight]:
    live = [t for t in tracks if not t.silent]
    fights = []
    for i, a in enumerate(live):
        for b in live[i + 1:]:
            for band, _, _ in BANDS:
                sa, sb = a.bands_db.get(band, -120), b.bands_db.get(band, -120)
                if sa < strong_db or sb < strong_db:
                    continue
                la, lb = band_level(a, band), band_level(b, band)
                if abs(la - lb) <= gap_db:
                    fights.append(Fight(a.name, b.name, band, round(abs(la - lb), 1), round(max(la, lb), 1)))
    return sorted(fights, key=lambda f: (-f.energy_db, f.gap_db))[:top]


def masked_bands(track: TrackReport, others: list[TrackReport]) -> list[str]:
    """Bands where the track carries real energy and the rest of the mix together is much louder."""
    out = []
    for band, _, _ in BANDS:
        if track.bands_db.get(band, -120) < -12:
            continue
        rest = [10 ** (band_level(o, band) / 10) for o in others if not o.silent]
        if not rest:
            continue
        rest_db = 10 * np.log10(sum(rest))
        if rest_db - band_level(track, band) >= MASK_DB:
            out.append(band)
    return out


def against_target(view_role: str, reading: TrackReport, vocal_lufs: float | None) -> list[str]:
    target = ROLE_TARGETS.get(view_role, ROLE_TARGETS["other"])
    notes = []
    if vocal_lufs is not None and view_role != "lead vocal":
        want = vocal_lufs + target["lufs_rel"]
        off = reading.lufs - want
        if abs(off) > LEVEL_TOLERANCE_DB:
            notes.append(f"{'loud' if off > 0 else 'quiet'} for a {view_role}: {off:+.1f} dB against the vocal")
    home = max(reading.bands_db, key=reading.bands_db.get) if reading.bands_db else ""
    if home and home != target["home"] and reading.bands_db.get(target["home"], -120) < reading.bands_db[home] - 3:
        notes.append(f"most energy in the {home}, a {view_role} usually lives in the {target['home']}")
    if target["hi_mono"] and reading.low_mono is not None and reading.low_mono < 0.8:
        notes.append(f"low end wide (correlation {reading.low_mono}); a {view_role} stays mono below 120 Hz")
    if reading.clipped:
        notes.append(f"{reading.clipped} clipped samples")
    return notes


def hardware_from_config() -> list[Hardware]:
    """The chain in front of Logic, from HIREMARCO_HARDWARE (a JSON list) in the env file."""
    raw = config.get("HIREMARCO_HARDWARE")
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except ValueError:
        return []
    return [Hardware(str(i.get("name", "")), str(i.get("role", "")), {k: str(v) for k, v in (i.get("settings") or {}).items()},
                     bool(i.get("live", True))) for i in items if i.get("name")]


def build(report: EarsReport, hardware: list[Hardware] | None = None) -> SessionView:
    readings = report.tracks
    views = []
    roles = {t.name: role_of(t.name, t) for t in readings}
    vocal = [t for t in readings if roles[t.name][0] == "lead vocal" and not t.silent]
    vocal_lufs = max(t.lufs for t in vocal) if vocal else None
    for t in readings:
        role, source = roles[t.name]
        others = [o for o in readings if o is not t]
        views.append(TrackView(t.name, role, source, t,
                               masked_bands(t, others) if not t.silent else [],
                               against_target(role, t, vocal_lufs) if not t.silent else []))
    return SessionView(views, collision_grid(readings), hardware if hardware is not None else hardware_from_config(),
                       list(report.mix_notes))


def where_to_fix(hardware: list[Hardware], already_recorded: bool) -> str:
    """The rule: printed audio is shaped in Logic; a live input is a hardware move first."""
    live = [h for h in hardware if h.live]
    if already_recorded or not live:
        return "in Logic: the audio is already printed, hardware cannot change it now"
    names = ", ".join(h.name for h in live)
    return f"on the hardware first ({names}): the signal is still live on the way in; Logic after that"


def summary(view: SessionView) -> str:
    lines = []
    for t in view.tracks:
        if t.reading.silent:
            lines.append(f"{t.name} ({t.role}): silent")
            continue
        line = f"{t.name} ({t.role}{'' if t.role_from == 'name' else ', guessed'}): {t.reading.lufs} LUFS, home {t.home_band}"
        if t.masked_bands:
            line += f"; masked in {', '.join(t.masked_bands)}"
        for note in t.against_target:
            line += f"; {note}"
        lines.append(line)
    for f in view.fights:
        lines.append(f"fight: {f.a} and {f.b} in the {f.band}, within {f.gap_db} dB at {f.energy_db} dB")
    for h in view.hardware:
        lines.append(f"hardware: {h.name} ({h.role}, {'live' if h.live else 'printed'}): "
                     + ", ".join(f"{k} {v}" for k, v in h.settings.items()))
    lines += [f"mix: {n}" for n in view.mix_notes]
    return "\n".join(lines)


def save(view: SessionView, path: Path) -> None:
    Path(path).write_text(json.dumps(view.as_dict(), indent=1))
