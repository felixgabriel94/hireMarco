id: S-MASTER-02
role: corrective_eq
job: mastering
triggers: ["problem_bands_db.mud > -8"]
claims: [R-AUD-0007, R-AUD-0005]

# Mud: a build-up in the low mids

**What to look for.** The audit's problem band "mud" (the low-mid region's
share of the whole), the low mids band against the references' deltas, and
the sub and bass bands beside it.

**Threshold.** Mud at -8 dB of the whole or above is a candidate; above -6
it is the strongest problem area and the first corrective move. Against a
reference set, a low-mids delta over +2 dB confirms it.

**Why.** A low-mid build-up masks the vocal and the bass's definition and
makes the whole dull; it is corrected before any dynamics so the compressor
does not clamp on it (master rulebook, order step 2). The move is broad and
small, because mastering is subtle (R-AUD-0005).

**When it applies.** The build-up is in the whole mix and the references sit
lower there. The vocal sits in the same region and the mix is already loud
and compressed.

**When it does not.** The genre wants the warmth and the references match;
or the build-up is one instrument, which is a mix move. A mix at -8 dB with
references at the same level is not mud, it is the record.

**The move.** Pro-Q 3, one Bell, frequency between 200 and 400 Hz where the
build-up centers, gain -0.5 to -2 dB scaled to the delta (a 2 dB delta
takes a 1 dB cut first), Q 0.7 to 1.5 (R-AUD-0007). Never a shelf here: a
shelf takes the bass with it.

**Expected effect.** The low mids band moves by the gain asked, the bass and
mids bands stay within 0.5 dB, the vocal reads clearer in the hearing
stack's words.

**Verify.** The print's bands against the mix; the low-mids delta closes
toward the references; the bench shows the gain earned.
