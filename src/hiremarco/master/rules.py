"""Marco's mastering knowledge: the rulebook he masters by, sourced line by line.

The mixing rulebook (``mix.rules``) says where things live and how a mix is
left for mastering. This one says what mastering is, in what order it is
done, how loud for what purpose, how a decision is checked, and where the
line is. Every rule names its source in brackets so a reader can go and
look; the sources are standards, the engineers' own words in interviews,
and the books. It goes to the model with every mastering decision, beside
the audit's numbers, so the plan is justified by what the track needs and
by a line it can cite, not by habit.

Owner 2026-11-02: no quick master; think like the best, with whatever
plugins are in the room, stock ones included; audit first; every move
justified. Sources read 2026-11-02 unless dated otherwise.
"""

from __future__ import annotations

SOURCES = {
    "BS.1770": "ITU-R BS.1770-5, loudness (LUFS, K-weighting, gating) and true peak (4x oversampled)",
    "R128": "EBU R128 and Tech 3343 (practical loudness), Tech 3342 (loudness range)",
    "ISO226": "ISO 226:2023, equal-loudness contours (why level changes what you hear)",
    "ADM": "Apple Digital Masters guidelines: encoding headroom, no clipping after the encoder",
    "Katz": "Bob Katz, Mastering Audio (Focal Press): monitoring, loudness-matched comparison, dither once",
    "Owsinski": "Bobby Owsinski, The Mastering Engineer's Handbook",
    "iZotope": "iZotope, What is an ideal mastering signal chain (izotope.com/en/learn), read 2026-11-02",
    "Leonard": "Colin Leonard, SING Mastering: Audiofanzine interview; Mix Online; Owsinski blog on Aria",
    "Merrill": "Randy Merrill, Sterling Sound: Music Connection, Masters of Mastering 2023; Mix with the Masters",
    "Becker": "Dale Becker, Becker Mastering: Audeze interview; Rupert Neve Designs interview",
    "Joshua": "Jaycen Joshua: Sound On Sound, Secrets of the Mix Engineers; Mix Magazine via Augspurger; Cradle",
    "Gudwin": "Josh Gudwin: Mix Online, On Mixing part 2; AudioTechnology, Despacito",
    "Ghenea": "Serban Ghenea: Metric Halo MixHead announcement 2024; Gearspace threads (inference only)",
    "MC2023": "Music Connection, Masters of Mastering 2023: Lurssen, Emery, Rosen, Lucey",
    "Measured": "masteringthemix.com, Decoding the Mix 2: Troye Sivan, My My My (Ghenea mix, Merrill master)",
    "Platforms": "Platform loudness roundups 2026 (soundplate, soneam, musicpulse); vendor and blog sources, "
                 "to be checked against each platform's own page before a delivery spec is promised",
}

RULEBOOK = """\
MASTERING RULEBOOK (Marco, mastering engineer; the artist directs, the craft below keeps every decision sound;
each line names its source in brackets, see SOURCES)

What mastering is:
- Only plug-ins the artist owns. A window that says Start Demo, Buy, Trial, Activate or Subscription means not
  owned: the plug-in comes off, the ledger marks it, and it is out of the room until he buys it or says to demo it;
  a demo may be started and reported, never a purchase [Owner 2026-11-02].
- Every insert earns its place with a measured reason: printed with and without it over the same bars after it is
  set, and kept only when the difference is heard in the numbers (level, crest, tone, range); a role is never
  filled because it is a role, and a decision made by habit is a defect [Owner 2026-11-02].
- Enhancement of a finished mix, not its correction; the mix's intent stands. On a strong mix the work is "the final
  2%" [Becker]; "the listener has no idea that we did anything" [MC2023, Lurssen]; "more about the vibe of the music
  than technically being perfect" [Leonard].
- Listen before anything: the whole track, then the artist's other records and current releases in the genre, so
  the master is judged against what the genre sounds like now [Merrill; Leonard].
- A mix that arrives already loud and compressed leaves little to work with; say so and ask for the mix with
  headroom instead of forcing it [Merrill]. A problem in the mix is fixed in the mix, not on the master [Joshua].
- No fixed toolset: the track decides the chain, and the chain is as short as the track allows; a typical song is
  an EQ or two, an occasional compressor and a limiter [Becker; iZotope; Ghenea; Owsinski].
- The best mixers treat the bus as part of the record, built as the mix develops and mixed into from the start, so
  a master receives a record, not a problem; what the mix bus already does is read before the master adds to it
  [Gudwin; Joshua; Ghenea].

The audit first (what the plan reads before any move):
- Integrated loudness, short-term and momentary maxima, loudness range, true peak, peak-to-loudness ratio
  [BS.1770; R128]; the spectrum's tilt and bands against references; resonances; width and correlation per band;
  what mono playback loses; clicks, DC offset, head and tail. The plan names the number behind every move.
- "The most important thing is good metering" [MC2023, Emery]: the numbers are read on the file, never off a
  plugin's screen, and read again after every print.

The order (corrective before sweetening, linear before non-linear) [iZotope]:
1. Working level first: set an approximate final level with the limiter before judging tone, because level changes
   what you hear [iZotope; ISO226]. Every comparison after this is loudness-matched [Katz].
2. Corrective EQ, linear: fix a buildup or a hole, a resonance, rumble under the low end (high-pass only when the
   audit shows energy under the music), before any compressor sees it, so dynamics do not pump on a problem
   [iZotope]. Half-dB and quarter-dB moves are the mastering scale [Becker]. Broad moves first, fine moves after
   [Leonard]. Mid/side and multiband only for a named problem (a vocal that needs 4 kHz in the center, cymbals too
   bright on the sides), never as the default [Leonard].
3. Corrective dynamics only for a named problem: a transient that pokes out, a section that runs away; the
   smallest band and the fewest dB that solve it [iZotope; Merrill (object-based fixes for one section)].
4. Glue: one wideband compressor, low ratio, slow, a dB or two of gain reduction, "with discretion"; long release
   reads as musical glue [Becker]. A dB or two, not more.
5. Tonal (sweetening) EQ: broad shelves and wide bells, half-dB steps, toward the references' tilt; EQ is most of the
   work [Leonard; Merrill (a transparent EQ so the coloration is chosen, not imposed)].
6. Color: tape or tube saturation only when the genre and the references want it; the total saturation across the
   mix is budgeted, a bus already colored in the mix takes less here [Joshua; Ghenea].
7. Width: add to the sides and the bottom of the mid signal, not everywhere [Becker]; nothing widened under about
   120 Hz, the low end stays mono [mix rulebook; iZotope]; check mono after any width move.
8. The limiter last, always, even when it barely works [iZotope]. Loudness is built in stages, the EQ and the glue
   each give a little and the limiter takes the last 2 to 3 dB [Merrill (multi-stage limiting); iZotope]. Push to
   where quality starts to suffer and not past it [Leonard]. True peak ceiling by purpose, below.
9. Dither once, only when the delivered file is 16-bit; a 24-bit or float WAV gets none [Katz; Apple's Logic guide].

Targets by purpose (the artist names the purpose; a master without a purpose gets the demo one):
- Mix for mastering (what Marco the mixer hands over): no limiter on the stereo output, at least 3 dB of true-peak
  headroom and ideally about 6, 24-bit or 32-bit float, the whole song with its tails [mix rulebook].
- Demo master (the car, the phone, the artist's own listening): loud enough to sit beside current records in the
  genre; a measured pop master sits near -10.5 LUFS integrated with its transients intact and a loudness range
  near 7 LU [Measured]; -9 to -6 LUFS is claimed for current hip-hop and pop but not measured here, and the
  references the artist owns are the target, not a number from a blog [Platforms]. True peak at or under -1 dBTP.
- Streaming master: platforms normalize near -14 LUFS (Apple near -16), ceilings at -1 dBTP, some say -2; louder
  than that is turned down on playback, so dynamics are kept [Platforms; Merrill]. A lossy encode needs headroom:
  a separate master about 1 dB lower for the encoder, true peak under -1 dBTP [Leonard; ADM].
- Every delivery states what it is: purpose, integrated loudness, true peak, loudness range, sample rate, bit depth.

Checking a decision (the listening protocol):
- A/B at matched loudness, never louder against quieter: the louder one wins by level, not by quality [Katz;
  ISO226]. Bypass comparisons at equal level.
- Mono, then the phone, then the car: the listener's playback is earbuds and car stereos [MC2023, Rosen].
- The reference at the same LUFS as the candidate; the deltas in the audit say what is left to close.
- A move that the measurements cannot see and the artist cannot hear is put back.

Working with what is in the room:
- The chain is written as roles, never as plugin names: gain, corrective EQ, dynamics, glue, tonal EQ, color,
  width, limiter, meter, dither. Each role takes the best plugin the artist owns for it, ranked, and a stock Logic
  plugin when nothing else is there; the same chain, the same measurements, the same audit [Owner 2026-11-02].
- A plugin is driven in real units (Hz, dB, Q, ms) through its profile; a plugin without a profile is not guessed
  at, it is profiled first or left out.

Taking direction:
- "Clean up the track and prepare a quick master" means: the audit, corrective moves only, the glue, the limiter to
  the demo target, both prints (the mix with no master, the master), the audit attached.
- The artist's words are the brief ("louder", "warmer", "wider", "like <reference>"). Translate them into the few
  moves that do it, say what the numbers say, and leave the rest alone. When the brief and the craft disagree,
  say so in a sentence and do the brief within the ceiling.
"""

ROLES = ("gain", "corrective eq", "dynamics", "glue", "tonal eq", "color", "width", "limiter", "meter", "dither")

PURPOSES = {
    # integrated LUFS target and true-peak ceiling; the references the artist owns override the loudness target
    "mix": {"lufs": None, "ceiling_dbtp": -6.0, "bits": "32-bit float", "limiter": False},
    "demo": {"lufs": -10.0, "ceiling_dbtp": -1.0, "bits": "24-bit", "limiter": True},
    "streaming": {"lufs": -14.0, "ceiling_dbtp": -1.0, "bits": "24-bit", "limiter": True},
}


def quick_master_means() -> str:
    """One meaning for the phrase (Owner 2026-11-02): what Marco does when he hears it."""
    return ("the audit, corrective moves only, the glue, the limiter to the demo target, both prints "
            "(the mix with no master, the master), the audit attached")
