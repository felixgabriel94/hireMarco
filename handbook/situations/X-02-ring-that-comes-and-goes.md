id: S-MIX-02
role: corrective_eq
job: mixing
triggers: ["peak: comes and goes"]
claims: [R-AUD-0006, R-AUD-0007]

# A ring that comes and goes

**What to look for.** On one take, a frequency that stands over its octave
in some windows and not in others: a sung note that rings only when it is
hit, a hat that pokes on its accents, a sibilant syllable.

**Threshold.** Over its octave by 6 dB or more in 20 to 60 percent of the
sounding windows (mix/takes.py, "comes and goes").

**Why.** A static cut at that note would thin the take everywhere for a
problem that is there a fifth of the time. A dynamic band cuts only when
the band crosses its threshold, so the hit is tamed and the rest of the
take is untouched (R-AUD-0006); this is what the artist asked for by name.

**When it applies.** The ring is an event, the windows it stands in are
the hits, and the note is not the melody's intended accent.

**When it does not.** The ring is the performance: an accented note the
artist wants to poke (then no cut, and the plan says so). The events are
sibilance above 5 kHz on a vocal: that is a de-esser's job (Pro-DS) before
a dynamic band.

**The move.** Pro-Q 3 on the take: one Bell at the note, dynamic range
negative and scaled to the excess (6 dB over takes -3 dB of range), the
auto threshold so the band follows the take's own level, Q 4 to 8
(R-AUD-0006, R-AUD-0007). Gain stays at 0 dB: nothing moves when the ring
is not ringing.

**Expected effect.** In the windows that rang, the note under 4 dB over its
octave; in the others, the take within 0.3 dB of the dry take.

**Verify.** The take printed and read again per window; the windows that
did not ring compared to the dry take.
