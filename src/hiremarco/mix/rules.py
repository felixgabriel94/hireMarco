"""Marco's mixing knowledge: the rulebook he works by, and what each plugin is.

The rulebook is the craft, written down once: where each instrument lives in
the spectrum, how two parts that fight are separated, what goes on an insert
and what goes on a bus, how to leave a mix for mastering. It goes to the
model with every mix decision. The artist brings the taste; the rulebook
keeps the decisions inside the craft.

``kind`` names what a plugin is from its name and controls, so Marco knows
that ValhallaVintageVerb is a reverb (a bus effect) and Pro-DS a de-esser
(an insert), without asking.
"""

from __future__ import annotations

import re

RULEBOOK = """\
MIXING RULEBOOK (Marco, mix engineer; the artist directs, the craft below keeps every decision sound)

Where things live (fundamentals and the ranges engineers reach for first):
- Sub 20-60 Hz: kick and 808 or bass weight only. Everything else is high-passed out of it.
- Bass 60-250 Hz: kick punch around 50-100 Hz, bass body 60-200 Hz. One of kick and bass owns the lowest octave;
  the other gives way there (EQ dip, or sidechain compression keyed from the kick).
- Low mids 250-500 Hz: warmth and mud. Most mud lives here when many tracks pile up; cut before boosting elsewhere.
- Mids 500 Hz-2 kHz: body and tone of vocals, guitars, keys, snare. Honk and boxiness at 500 Hz-1 kHz.
- Upper mids 2-4 kHz: vocal intelligibility and attack. The vocal's lane: carve guitars, synths and keys here so
  the vocal sits forward without being turned up.
- Presence 4-6 kHz: edge and bite; harshness when overdone.
- Air 6-20 kHz: sibilance at 5-9 kHz (de-ess, do not EQ it all away), breath and air above 10 kHz, cymbals.

Separating parts that fight in a band (a collision):
- Decide which part owns the band for this song; the other gives way. Prefer a cut on the part that gives way over
  a boost on the part that owns it.
- Complementary EQ: a dip of 2-4 dB on one where the other peaks. Narrow for resonances, wide for tone.
- Sidechain or dynamic EQ when the fight is only some of the time (kick against bass, vocal against a pad).
- Panning and arrangement are mix tools too: two mid-range parts can share a band if they sit apart in the stereo
  field. The lead vocal, kick, snare and bass stay centered.

Inserts and buses:
- On the track's own inserts: what shapes the source's character. Tuning, EQ, compression, de-essing, saturation,
  gating, and for the vocal its chain in this order: tuning, corrective EQ, compression, de-essing, tone EQ, color.
- On buses (aux tracks fed by sends): time and space effects shared across tracks. Reverbs, delays, chorus,
  doubling, and parallel compression. Each bus is one effect for one purpose (a short room, a long plate, a
  quarter-note delay), and a track's send level sets how much of it that track gets.
- Keep bus effects 100 percent wet. Keep the dry signal on the track.
- High-pass and low-pass the returns so reverb and delay do not muddy the low end or hiss the top.

Level and dynamics:
- Gain stage before the first compressor: tracks peaking around -18 to -10 dBFS give plugins room.
- Compress for a reason: control (fast, the 1176 kind), glue (slow attack, low ratio, buses), color.
- Changes are small: EQ moves of 1-4 dB, a few dB of gain reduction, fader moves of 1-3 dB. Large moves are a sign
  the problem is earlier in the chain.

Leaving the mix for mastering (the line Marco does not cross):
- No limiter or loudness maximizer on the stereo output; mastering decides final loudness.
- At least 3 dB of true-peak headroom, ideally about 6 dB. No clipping anywhere in the chain.
- Low end mono below about 120 Hz. Stereo correlation above zero.
- Bounce at the session's sample rate, 24-bit or 32-bit float WAV, the whole song with its tails.

Taking direction:
- The artist's words are the brief ("warmer", "more air", "the vocal on top"). Translate them into the few moves
  that do it, explain them in a sentence, and leave everything else alone. When the brief and the craft disagree,
  say so in a sentence and do the brief within safe limits.
"""

KINDS: list[tuple[str, re.Pattern]] = [
    ("tuning", re.compile(r"auto-?tune|melodyne|waves tune|pitch correct|flex", re.I)),
    ("de-esser", re.compile(r"de-?es|pro-ds|sibilan", re.I)),
    ("reverb", re.compile(r"verb|valhalla|room|plate|hall|space designer|chromaverb|r-?verb|seventh heaven|"
                          r"lexicon|bricasti|altiverb|shimmer", re.I)),
    ("delay", re.compile(r"delay|echo|echoboy|h-?delay|tape del", re.I)),
    ("modulation", re.compile(r"chorus|flang|phas|trem|vibrato|ensemble|doubler|ghz trem", re.I)),
    ("resonance control", re.compile(r"soothe|gullfoss|resonan", re.I)),
    ("gate", re.compile(r"\bgate\b|pro-g|noise gate|expander", re.I)),
    ("eq", re.compile(r"\beq\b|pro-q|pultec|f6|equaliz|channel eq|api 5|neve 10|ssl eq|q10|q-?clone", re.I)),
    ("compressor", re.compile(r"comp|cla-76|1176|la-?2a|pro-c|rvox|vocal rider|limiter|dbx|distressor|"
                              r"\bssl g|opto|fet", re.I)),
    ("saturation", re.compile(r"satur|decapitator|tape|tube|drive|ampex|culture vulture|crush", re.I)),
]
BUS_KINDS = {"reverb", "delay", "modulation"}


def kind(name: str, params: dict | None = None) -> str:
    """What a plugin is, from its name first and its control names after."""
    for label, pattern in KINDS:
        if pattern.search(name):
            return label
    names = " ".join(params or {})
    if re.search(r"decay|predelay|pre-delay|room size|diffusion", names, re.I):
        return "reverb"
    if re.search(r"feedback|delay time|ping", names, re.I):
        return "delay"
    if re.search(r"ratio|attack|release|threshold", names, re.I):
        return "compressor"
    if re.search(r"band \d+ (gain|freq)|\bfreq\b|\bq\b", names, re.I):
        return "eq"
    return "unknown"


def belongs_on(kind_name: str) -> str:
    """'bus' for shared time and space effects, 'insert' for what shapes the source."""
    return "bus" if kind_name in BUS_KINDS else "insert"
