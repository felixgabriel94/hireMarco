"""Expert profiles: what a plugin is for, how its controls read in real units, and its recipes.

A profile is checked against the controls Logic actually exposes before it is
used (``fits``), so nothing in it refers to a control the plugin does not
have. Units come from the raw values Logic reports, worked out against the
plugin's defaults in the live read of 2026-10-28:

Pro-Q 3 (FabFilter): Frequency raw r is 10 Hz x 2^(r/1000) (the default 6644
reads 1000 Hz, the range 0-11551 spans 10 Hz-30 kHz); Gain and Dynamic Range
raw 30000 is 0 dB at 1000 per dB (+-30 dB); Q raw r is 0.025 x 1600^(r/10000)
(the default 5000 reads Q 1.0). These are inferences from defaults and ranges,
labelled as such, and the read-back after every set catches a wrong one.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field


@dataclass
class Unit:
    unit: str
    to_unit: callable
    to_raw: callable


@dataclass
class Profile:
    name: str
    matches: re.Pattern
    summary: str
    features: list[str]
    units: list[tuple[re.Pattern, Unit]] = field(default_factory=list)
    recipes: dict[str, str] = field(default_factory=dict)
    needs: list[str] = field(default_factory=list)  # controls that must exist for the profile to apply

    def fits(self, controls: list[str]) -> bool:
        return all(any(re.fullmatch(n, c) for c in controls) for n in self.needs)

    def unit_for(self, control: str) -> Unit | None:
        for pattern, unit in self.units:
            if pattern.fullmatch(control):
                return unit
        return None


HZ = Unit("Hz", lambda r: round(10 * 2 ** (r / 1000), 1), lambda hz: 1000 * math.log2(max(hz, 10) / 10))
DB = Unit("dB", lambda r: round((r - 30000) / 1000, 2), lambda db: 30000 + db * 1000)
Q = Unit("Q", lambda r: round(0.025 * 1600 ** (r / 10000), 3), lambda q: 10000 * math.log(max(q, 0.025) / 0.025, 1600))

PRO_Q3 = Profile(
    name="FabFilter Pro-Q 3",
    matches=re.compile(r"pro-?q ?3", re.I),
    summary=("24-band EQ for surgical and tonal work. Each band can be static or dynamic, and a dynamic band "
             "can listen to its own track or to another track through the external side chain, which is how an "
             "expert makes room between two parts only when they collide."),
    features=[
        "Add a band: set 'Band N Used' to on for a band that is off, then its Frequency, Gain and Q.",
        "Dynamic EQ: 'Band N Dynamics Enabled' on; 'Band N Dynamic Range' is how far the band moves (negative "
        "ducks); 'Band N Threshold' is where it starts. The band's static Gain is the resting point.",
        "External side chain per band: 'Band N External Side Chain' on makes that band's dynamics follow the "
        "side-chain input (set in Logic's plugin header) instead of the track itself.",
        "Frequency in Hz (10 Hz to 30 kHz, log), Gain and Dynamic Range in dB (+-30), Q from 0.025 to 40.",
        "Collision display and spectrum grab are in Pro-Q's own window, not controls; Marco's ears measure "
        "collisions instead.",
    ],
    units=[(re.compile(r"Band \d+ Frequency"), HZ), (re.compile(r"Band \d+ Gain"), DB),
           (re.compile(r"Band \d+ Dynamic Range"), DB), (re.compile(r"Band \d+ Q"), Q)],
    recipes={
        "duck the bass under the kick": (
            "On the bass's Pro-Q 3: take a band that is not used, set Used on, Frequency at the kick's fundamental "
            "(from the measurements, usually 45-90 Hz), Gain 0 dB, Q about 1.4, Dynamics Enabled on, Dynamic "
            "Range -3 to -6 dB, External Side Chain on. Logic's side-chain input on that Pro-Q is the kick track. "
            "The bass gives way only while the kick sounds; between hits it keeps its weight."),
        "make room for the vocal in a dense part": (
            "On the competing track (guitars, keys, pads): a dynamic band at 2-4 kHz, Gain 0 dB, Q about 1, "
            "Dynamic Range -2 to -4 dB, External Side Chain on, side-chain input the lead vocal."),
        "tame a resonance only when it rings": (
            "A narrow dynamic band (Q 6-10) on the resonant frequency with negative Dynamic Range and its own "
            "signal as the trigger; static Gain stays 0 dB."),
    },
    needs=[r"Band 1 Frequency", r"Band 1 Gain", r"Band 1 Dynamic Range", r"Band 1 External Side Chain"],
)

PROFILES = [PRO_Q3]


def profile_for(plugin: str, controls: list[str]) -> Profile | None:
    for p in PROFILES:
        if p.matches.search(plugin) and p.fits(controls):
            return p
    return None


def for_model(profile: Profile) -> dict:
    return {"expert_profile": profile.name, "summary": profile.summary, "features": profile.features,
            "recipes": profile.recipes, "units": sorted({u.unit for _, u in profile.units})}
