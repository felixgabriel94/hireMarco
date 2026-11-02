"""Marco's mixing knowledge: the rulebook he works by, sourced line by line, and what each plugin is.

The rulebook is the craft, written down once: where each instrument lives in
the spectrum, how two parts that fight are separated, what goes on an insert
and what goes on a bus, how the bus is treated, how to leave a mix for
mastering. It goes to the model with every mix decision. The artist brings
the taste; the rulebook keeps the decisions inside the craft. Every line
names its source in brackets (see SOURCES); a number no opened source backs
is marked as a starting point, tuned by ear and not law. Owner 2026-11-02:
the mixer is held to the same standard as the mastering engineer.

``kind`` names what a plugin is from its name and controls, so Marco knows
that ValhallaVintageVerb is a reverb (a bus effect) and Pro-DS a de-esser
(an insert), without asking.
"""

from __future__ import annotations

import re

SOURCES = {
    "WH2008": "Paul White and Matt Houghton, What's The Frequency? A Guide To Effective EQ, Sound On Sound, Dec 2008",
    "White2007": "Paul White, Tricks To Make Your Drums Sparkle, Sound On Sound, Jun 2007",
    "White2011": "Paul White, Mix Tips: Kick and Bass, Sound On Sound, 2011",
    "Senior2008": "Mike Senior, Q: What should I EQ to improve my muddy mixes?, and Mix Rescue, Sound On Sound, 2008",
    "Senior2010": "Mike Senior, Creating and Using Synth Pad Sounds, Sound On Sound, 2010",
    "Senior2012": "Mike Senior, Mixing Bass, Sound On Sound, 2012",
    "Senior2013": "Mike Senior, Mix Rescue (Wronguns Media; Cristina Vane), Sound On Sound, 2013",
    "Senior2015": "Mike Senior, Q: What will give my electronic tracks real low-end impact?, Sound On Sound, 2015",
    "Walden2006": "Mark Walden, Processing Acoustic Guitars, Sound On Sound, 2006",
    "Morley2020": "Morley, Making Space In Your Mix, Sound On Sound, 2020",
    "Owsinski": "Bobby Owsinski, The Mixing Engineer's Handbook, 4th ed., the octave chart as published on his blog",
    "FabFilter2022": "de Boer, Perception of frequency and loudness, FabFilter Learn, 2022 (ISO 226 contours)",
    "Mellor2009": "David Mellor, Should you pan low-frequency instruments?, Audio Masterclass, 2009",
    "Joshua": "Jaycen Joshua, Sound On Sound, Secrets of the Mix Engineers; Mix Magazine via Augspurger",
    "Gudwin": "Josh Gudwin, Mix Online, On Mixing part 2; AudioTechnology, Despacito",
    "Ghenea": "Serban Ghenea, Metric Halo MixHead announcement 2024; the John Hanes Q&A as summarized (inference)",
    "start": "a starting point: Marco's reasoning or common practice, no opened source; tune by ear, not law",
}

RULEBOOK = """\
MIXING RULEBOOK (Marco, mix engineer; the artist directs, the craft below keeps every decision sound; each line names
its source in brackets, see SOURCES; [start] marks a number nothing opened backs yet)

How the ear weighs it:
- Hearing is most sensitive at 2-4 kHz; lows must be much louder to sound as loud, and the gap shrinks as playback
  gets louder, so the low end is judged at one fixed monitor level, loud for the lows and quiet for the mids
  [FabFilter2022]. Every A/B is loudness-matched, or the louder one wins by level.
- The octaves in the words engineers use: 31 Hz rumble and chest, 63 bottom, 125 boom and warmth, 250 fullness and
  mud, 500 honk, 1k whack, 2k crunch, 4k edge, 8k sibilance and definition, 16k air [Owsinski].

Where things live (fundamentals, and the ranges engineers reach for first):
- The bass range has two owners, the kick and the main bass; everything else is filtered out of it, even parts that
  sound bright, because they hide low-level bass [Morley2020]. Low frequencies use most of a mix's headroom
  [Senior2008]. Two exceptions: a low shelf can do a more musical job than a high-pass [Senior2008], and in a sparse
  folk or singer-songwriter arrangement the bass gives way where the piano or the acoustic guitar leads [Senior2012].
- Kick: weight 60-90 Hz, boxiness 150-200 Hz, beater 2.5-4 kHz; high-pass below 30-40 Hz for headroom; a dip near
  220 Hz leaves room for the bass [WH2008; White2007; White2011]. Band default: the kick owns 70-90 Hz and the bass
  owns 220-300 Hz; club alternative: the bass mainly below 70 Hz and the kick higher [White2011; Senior2015]. One
  owner per song, named [start].
- Bass: bottom 60-80 Hz, character 220-300 Hz (what carries it on small speakers), attack 0.7-1 kHz, pop 2.5 kHz
  [WH2008; White2011]; high-pass 20-30 Hz under any low shelf; booming notes under 100 Hz cut narrow, Q near 8; no
  boost below 40 Hz where the part has no energy, a sub-octave instead; only one bass layer carries energy below
  100 Hz; the bass stays centered [Senior2012].
- Low mids 250-500 Hz: fullness and mud [Owsinski]; the whole kit often wants a dip at 200-500 Hz [White2007]; cut
  before boosting elsewhere [Senior2008].
- Mids 500 Hz-2 kHz: body and tone of vocals, guitars, keys and snare; honk at 500 Hz [Owsinski]; snare body near
  240 Hz, bite 2 kHz, crisp 4-8 kHz [WH2008].
- The vocal's lane: presence near 5 kHz [WH2008]; pads are recessed 4-6 dB at 3-4 kHz to sit behind it
  [Senior2010]; a part is dipped where the vocal sits before it goes in [Morley2020]. Where exactly the lane sits is
  this song's vocal, read from its spectrum, not a fixed band [start].
- Presence and air: hi-hat shimmer 7.5-12 kHz and vocal sibilance 7.5-10 kHz share a region, the first pair to check
  when a vocal sounds spitty [WH2008]; hat and cymbal harshness tamed at 3-6 kHz [White2007]; de-ess sibilance, do not
  EQ it all away [start].
- Acoustic guitar: by role. Featured, it keeps its 80-100 Hz weight and 240 Hz body with a high-pass at 48-75 Hz, and
  the bass yields [WH2008; Senior2013; Senior2012]; strummed in a band, high-pass near 100 Hz [Senior2008;
  Walden2006]; boom in 100-300 Hz cut 2-3 dB, boxiness at 500 Hz, presence 5-7 kHz over top boosts when cymbals are
  busy [Walden2006; Senior2013].
- Piano: 27.5 Hz to 4.2 kHz in fundamentals; featured it keeps its 80-120 Hz bottom, in a band a low shelf near 90 Hz
  for the bass; shrillness 5-7.5 kHz, attack near 10 kHz [WH2008; Senior2008; Senior2012].
- Pads: nothing useful below about 200 Hz, a gentle high-pass from about 300 Hz; width is freer on pads; faded down
  where a thin texture would expose them [Senior2010]. Soft synths load in stereo; each is checked for whether it
  needs it [Morley2020].
- A filter's number reads at its -3 dB point, so a 100 Hz high-pass still acts around 280 Hz [Senior2008]. Bracket
  each part: the lows and highs it does not need, 12-24 dB/oct [WH2008; Morley2020].

Separating parts that fight in a band (a collision):
- Build in order of importance: each part is added against the more important one, and only what the important
  part does not miss is cut [Senior2008]. Prefer a cut on the part that gives way over a boost on the owner [start].
- Complementary EQ: a dip of 2-4 dB on one where the other peaks; narrow for resonances, wide for tone [start].
- Sidechain or dynamic EQ when the fight is only some of the time: the bass ducked 2-3 dB per kick hit, a pad under
  the vocal [Senior2012; White2011].
- Panning and arrangement are mix tools too; low-frequency sounds stay centered (panning one side costs about 6 dB
  of maximum level) [Mellor2009; Senior2012]; a mono part saves space, swept left to right and left where it sounds
  loudest [Morley2020]. The lead vocal, kick, snare and bass stay centered [start].

Inserts and buses:
- On the track's own inserts: what shapes the source's character. Tuning, EQ, compression, de-essing, saturation,
  gating, and for the vocal its chain in this order: tuning, corrective EQ, compression, de-essing, tone EQ, color
  (the order the top vocal chains follow: Gudwin's 1176, de-esser, Massive Passive, strip) [start; Gudwin].
- On buses (aux tracks fed by sends): time and space effects shared across tracks. Reverbs, delays, chorus,
  doubling, and parallel compression. Each bus is one effect for one purpose, and a track's send level sets how
  much of it that track gets. Bus effects 100 percent wet; the dry signal on the track [start]. Delays over reverb
  keep a mix clean; no reverb on rap vocals [Joshua]. High-pass and low-pass the returns; a drum reverb rolled off
  below about 200 Hz [White2007].
- Parallel compression on the kick and the snare, blended with the dry, so nothing goes thin [Joshua].
- Groups into the bus: rhythm, music and vocals as three stereo pairs before the stereo sum, so a change to one
  stem does not surprise the bus compressor [Joshua].

The mix bus:
- The bus is part of the record: mixed into from the start [Ghenea; Joshua], or kept mostly inactive early and
  built as the mix develops [Gudwin]; a bus compressor (a 33609 or an SSL kind) opens it [Gudwin]; the total
  saturation across the mix is a budget, a tape stage on the bus takes from it [Ghenea; Joshua]. When the mix
  does not hit the bus right, the mix is fixed, not the bus [Joshua].
- Whole sections lifted about 1 dB for a chorus or an outro: dynamics are the pop mix [Joshua].

Level and dynamics:
- Gain stage before the first compressor: tracks peaking around -18 to -10 dBFS give plugins room [start].
- Compress for a reason: control (fast, the 1176 kind), glue (slow attack, low ratio, buses), color [start].
- Changes are small: EQ moves of 1-4 dB, a few dB of gain reduction, fader moves of 1-3 dB. Large moves are a sign
  the problem is earlier in the chain [start].

Leaving the mix for mastering (the line Marco does not cross):
- No limiter or loudness maximizer on the stereo output; mastering decides final loudness [mastering rulebook].
- At least 3 dB of true-peak headroom, ideally about 6 dB. No clipping anywhere in the chain [mastering rulebook].
- Low end centered and mono: the principle is cited [Mellor2009; Senior2012], the 120 Hz line is a starting point
  [start]. Stereo correlation above zero.
- Bounce at the session's sample rate, 24-bit or 32-bit float WAV, the whole song with its tails [mastering rulebook].
- A mix that arrives loud and compressed leaves the mastering engineer little to work with [mastering rulebook].

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
