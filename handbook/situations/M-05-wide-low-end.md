id: S-MASTER-05
role: width
job: mastering
triggers: ["finding: low end below 120 Hz is wide", "finding: mono playback loses"]
claims: [R-AUD-0015, R-AUD-0005]

# A wide low end, or a mix that loses in mono

**What to look for.** The low-end correlation (below 120 Hz) and the
per-band width; what folding to mono costs in LU.

**Threshold.** Low-end correlation under 0.8, or a mono loss of 1.5 LU or
more.

**Why.** Wide bass cancels on club systems and mono phones and makes the
low end unstable; the low end stays mono and width is added above it
(master rulebook, order step 7). A mono loss means something wide is out
of phase and will vanish on a single speaker.

**When it applies.** The width is in the bass itself (a stereo bass or a
wide 808), the song is for playback everywhere.

**When it does not.** The width is a wide pad or reverb and the bass under
it is already mono (correlation fine under 120 Hz): then it is a feature.
A mono loss that comes from one part is a mix move (a polarity or a stereo
effect on one take).

**The move.** Ozone 11 Imager, low band width toward mono (a negative
width on the band under 120 Hz, scaled to the correlation: 0.59 takes most
of the way to mono, 0.75 a gentle step), nothing changed above; or the
Manley Variable Mu in mid/side with the side compressed only when the
problem is dynamic (R-AUD-0015).

**Expected effect.** Low-end correlation above 0.9, mono loss under 1 LU,
upper bands' width unchanged within 1 dB.

**Verify.** The print's correlation and width per band against the mix;
the mono fold's loudness; the bench shows the insert earned.
