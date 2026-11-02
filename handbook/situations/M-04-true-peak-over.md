id: S-MASTER-04
role: limiter
job: mastering
triggers: ["finding: true peak", "lufs < target - 0.5"]
claims: [R-AUD-0001, R-AUD-0002, R-AUD-0003, R-AUD-0008, R-AUD-0009, R-AUD-0010, R-AUD-0011]

# Level and ceiling: the limiter last, to the purpose

**What to look for.** Integrated loudness against the purpose's target
(demo, streaming, mix for mastering); the true peak against the ceiling;
PLR and crest, which say how much of the climb is peaks and how much is
body; the loudness range.

**Threshold.** Integrated loudness more than 0.5 LU under the target, or
true peak over the ceiling.

**Why.** The ceiling is a true-peak ceiling because inter-sample peaks clip
converters and encoders (R-AUD-0011; R-AUD-0002); platforms turn a loud
master down and ask for -1 dBTP, -2 dBTP when louder than -14 LUFS
(R-AUD-0003). Loudness is built in stages and the limiter takes the last
2 to 3 dB (master rulebook, order step 8).

**When it applies.** Every master with a purpose; a mix for mastering gets
no limiter at all.

**When it does not.** The mix arrives already limited hard (PLR under
8 dB): say so and ask for the mix with headroom rather than limiting a
limited file (master rulebook, Merrill line). A purpose of "mix" or no
purpose named by the artist.

**The move.** Pro-L 2 last on the chain: Output Level at the purpose's
ceiling in dBTP with True Peak Limiting on and 4x oversampling (R-AUD-0011);
Style Modern or Transparent for a pop or hip-hop demo, Dynamic when the
crest must survive, never Bus or Aggressive on a master without a reason
written (R-AUD-0009); Lookahead near the default, longer when the chain
check shows distortion, shorter only when loudness is short and the bench
stays clean (R-AUD-0010); Gain set so the integrated loudness lands at the
target after the gain stage and the glue have given their part; the exact
dB from the measured gap, not a habit (R-AUD-0008).

**Expected effect.** Integrated loudness within 0.5 LU of the target, true
peak at or under the ceiling, loudness range reduced by no more than the
plan said, no beat-rate pumping.

**Verify.** The print's loudness and true peak read on the file, never off
the plug-in (master rulebook); verify.compare for pumping and crest; a
second round with the exact remaining gap when the target is missed.
