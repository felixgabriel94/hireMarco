id: S-MASTER-07
role: corrective_eq
job: mastering
triggers: ["finding: energy under 30 Hz"]
claims: [R-AUD-0007]

# Rumble: energy under the music

**What to look for.** The audit's rumble band (under 30 Hz) as a share of
the whole, and the sub band beside it.

**Threshold.** The audit's rumble finding (energy under 30 Hz above its
threshold); otherwise no high-pass at all.

**Why.** Energy under the music eats limiter headroom and shakes speakers
without being heard; a high-pass is a corrective move taken only when the
audit shows the energy (master rulebook, order step 2), never by habit.

**When it applies.** The rumble finding is present.

**When it does not.** No finding: the sub is the record (an 808's
fundamental sits at 30 to 60 Hz and a high-pass set by habit thins it).

**The move.** Pro-Q 3, Low Cut at 20 to 28 Hz, slope 12 to 24 dB per
octave (R-AUD-0007), below the lowest fundamental in the song.

**Expected effect.** The rumble share drops below the threshold; the sub
band within 0.5 dB of the mix.

**Verify.** The print's rumble and sub bands against the mix; the bench.
