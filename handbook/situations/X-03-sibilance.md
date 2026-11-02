id: S-MIX-03
role: dynamics
job: mixing
triggers: ["problem_bands_db.sibilance > -10"]
claims: [R-AUD-0006]

# Sibilance on a vocal take

**What to look for.** The take's sibilance band share (5 to 10 kHz) and
the hearing stack's sharpness in acum; the ess syllables as events in the
per-window read.

**Threshold.** Sibilance band at -10 dB of the whole or above on a vocal
take, or sharpness over 2 acum.

**Why.** Esses that poke are the first thing a listener hears on earbuds,
and a compressor after them makes them louder; a de-esser or a narrow
dynamic band tames only the ess, only when it happens (R-AUD-0006).

**When it applies.** A vocal or a hat-heavy part; the events sit between 5
and 10 kHz.

**When it does not.** The whole top is bright (a tilt problem, S-MASTER-03
on the mix bus, or a shelf on the take): a de-esser on a bright take dulls
the esses and leaves the brightness.

**The move.** Pro-DS on the take first (threshold set so the loudest ess is
caught by 3 to 6 dB, range 6 dB, the band 5 to 10 kHz as the artist's own
chain does); or Pro-Q 3 with a narrow dynamic Bell at the measured ess
frequency, dynamic range -3 to -6 dB, auto threshold (R-AUD-0006).

**Expected effect.** Sibilance band down by the range asked on the ess
windows, the rest of the take unchanged, sharpness under 2 acum.

**Verify.** The take read again per window; sharpness from the hearing
stack; the ess windows against the dry take.
