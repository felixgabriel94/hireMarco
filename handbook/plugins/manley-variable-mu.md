# UAD Manley Variable Mu (authorized; claim R-AUD-0015)

The glue compressor in the artist's room, the one the plan picks when the
mix asks for glue (situation S-MASTER-06). From the UAD Plug-Ins Manual
installed on this Mac, read 2026-11-02.

## What it is

A dual-triode variable-gain compressor re-biased by its own sidechain,
transparent and smooth; its purpose is the mix bus. Linked stereo makes
both channels compress the same amount at any instant, so a one-sided
transient does not shift the image; input and output matrices allow
mid/side work.

## The controls, and how Marco sets them

- **Dual Input**: higher is more colored, lower more transparent. On a
  master, low.
- **Threshold**: toward MIN lowers the threshold and increases compression.
  Marco lowers it only until the gain reduction meter shows 1 to 2 dB on the
  loudest bars of the chain check, and writes that number.
- **Attack** and **Recovery**: unmarked, 0 to 10, "designed to be set by
  ear": on a master, slow attack and medium to slow recovery, proven on the
  eight-bar chain check against beat-rate pumping.
- **Output**: set so the bench compares at matched level.
- **Left-Right / Mid-Side** switches and **Sidechain Link**: L-R linked for
  glue; M-S only for a named stereo problem (a side that runs away).
- **Headroom** (UAD-only): the operating level; left at default unless the
  input runs hot.
- **Mix**: parallel compression; not on a master.

## When it does not go on

LRA under 5 LU, a bus compressor already in the mix, or a bench that shows
nothing earned: then it comes off (the artist's rule, 2026-11-02).
