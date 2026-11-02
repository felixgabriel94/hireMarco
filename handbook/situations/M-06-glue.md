id: S-MASTER-06
role: glue
job: mastering
triggers: ["loudness_range > 8"]
claims: [R-AUD-0015, R-AUD-0005, R-AUD-0010]

# Loose dynamics: when glue earns its place, and when it does not

**What to look for.** The loudness range (LRA), the crest, and parts that
jump (short-term maximum far above integrated); whether the mix bus
already carries a compressor (the chain read of the output strip and the
mix's own record).

**Threshold.** LRA over 8 LU or a short-term maximum more than 6 LU over
the integrated loudness is loose; LRA under 5 LU is steady and gets no
glue (master rulebook, order step 4).

**Why.** One wideband compressor, low ratio, slow, a dB or two of gain
reduction, holds a loose mix together; a steady mix compressed again only
loses movement, and a compressor that earns nothing on the bench comes off
(the artist's rule, 2026-11-02; R-AUD-0005).

**When it applies.** LRA high, no bus compressor in the mix, parts that
jump in level.

**When it does not.** LRA under 5 LU; a bus compressor already in the mix;
a hip-hop or pop mix whose transients are the record (then the limiter does
the level work alone, R-AUD-0010).

**The move.** UAD Manley Variable Mu (R-AUD-0015): stereo linked, L-R;
Threshold toward MIN only until the gain reduction meter shows 1 to 2 dB on
the loudest bars; Attack slow, Recovery medium to slow (set by ear on the
chain check: the bars of the chorus); Dual Input low for transparency;
Output to match the bypass level for the bench. In mid/side only for a
named stereo problem.

**Expected effect.** LRA down by 1 to 2 LU, crest down by no more than
2 dB, no beat-rate pumping, tilt unchanged.

**Verify.** The bench: printed with and without the compressor over the
same bars, loudness-matched; kept only when LRA or the jump measurably
closes and nothing pumps (verify.compare).
