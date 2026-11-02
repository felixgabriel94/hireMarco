# FabFilter Pro-L 2 (version 2.21 installed; claims R-AUD-0008 to R-AUD-0013)

The true-peak limiter at the end of every master chain. From the help
installed with the plug-in on this Mac, read 2026-11-02.

## What the controls mean

- **Gain** (dB): the loudness control; it lowers the limiting threshold and
  raises the output gain at once, so the audio gets louder under the same
  ceiling. Reverse-linked to Output Level for an A/B at equal volume
  (R-AUD-0008). Marco sets it from the measured gap to the target after the
  gain stage and the glue have given their part.
- **Output Level** (dBTP when True Peak Limiting is on): the ceiling. -1.0
  dBTP for EBU R128 and for a streaming master; the platform asks for -2.0
  dBTP when the master is louder than -14 LUFS (R-AUD-0003, R-AUD-0011).
- **True Peak Limiting** on, with **Oversampling** 4x: inter-sample peaks
  within about 0.1 dB with a Lookahead of at least 0.1 ms (R-AUD-0011).
- **Style**: Modern (default, all-purpose, clean and very loud at near-zero
  lookahead), Transparent (true to the source, rock and pop), Dynamic
  (transients enhanced first), Allround, Punchy (apparent, some pumping;
  single tracks and beat-driven music), Aggressive (near clipping; EDM,
  rock, metal, pop), Bus (glue, pump, squash; not for a master unless the
  record wants it), Safe (no distortion ever; delicate material)
  (R-AUD-0009). None is better than another; the bench decides.
- **Lookahead** (ms): short keeps transients and loudness at the risk of
  distortion; long is safer and less loud (R-AUD-0010).
- **Attack** and **Release** (ms): short attack with long release is safer
  and cleaner but can pump and dull; long attack with short release is
  louder and more present at the risk of distortion (R-AUD-0010). Pumping
  measured by the verifier at the beat or bar rate means a longer release
  or a lighter Gain, never more.
- **Channel Linking**: Transients often under 100 percent, Release starts
  at 100 percent (R-AUD-0010).
- **Dither**: 16 bits only for a 16-bit delivery; Off for a 24-bit or float
  file (R-AUD-0013).
- **Loudness meter**: targets -9, -14, -23, -24 LUFS as the maker describes
  them; the record is read on the file, never off this meter (R-AUD-0012;
  master rulebook).

## The controls as Logic lists them (observed in the run records, 2026-11-02)

`Gain`, `Output Level`, `Lookahead`, `Attack`, `Release`, `Style`, the
channel linking pair, `Oversampling`, `True Peak Limiting`, `Dither`,
`Noise Shaping`, `Unity Gain`; the plug-in prints the unit beside each
value and Marco sets them in that unit.
