id: S-MIX-01
role: corrective_eq
job: mixing
triggers: ["peak: stays"]
claims: [R-AUD-0007, R-AUD-0006, R-AUD-0014]

# A ring that stays through the take

**What to look for.** On one take, read in one-second windows: a frequency
that stands over its octave in most of the windows the take sounds in,
named by its note and how it sits in the song's key.

**Threshold.** Over its octave by 6 dB or more in at least 60 percent of
the sounding windows (mix/takes.py, "stays").

**Why.** A ring that is always there is part of the take's tone, not an
event: the room, the mic, a resonance of the instrument. A static cut at
the note removes it everywhere at once and nothing moves (R-AUD-0007). A
dynamic band would chase a problem that does not move (R-AUD-0006).

**When it applies.** The note is off the key, or in the key but not a
chord tone, or on a chord tone and still over 9 dB above its octave: a
ring that loud is a problem even on the right note.

**When it does not.** The ring is a chord tone under 9 dB over its octave
and the part is the instrument that carries that note (a bass on its
fundamental, a pad on its chord): then it is tone, and the plan says so.
A take whose peak sits under 60 Hz or above 8 kHz is out of the detector's
range and is judged by ear.

**The move.** Pro-Q 3 on the take: one Bell at the note, typed as the note
with its cents in the plug-in's own field ("B3+49"), gain scaled to the
excess (half the measured dB over the octave as the first cut: 6 dB over
takes -3 dB), Q 6 to 12, narrower for a purer ring; a Notch with slope 24
to 48 dB per octave when the ring is pure and must go entirely
(R-AUD-0007). soothe2 with high selectivity and sharpness when there are
three or more rings on one take (R-AUD-0014).

**Expected effect.** The take's peak list no longer carries the note, or
carries it under 4 dB over its octave; the take's level within 0.5 dB.

**Verify.** The take printed and read again with mix/takes.py; the delta
against the dry take at matched loudness; nothing above or below the ring
moved by more than 0.5 dB.
