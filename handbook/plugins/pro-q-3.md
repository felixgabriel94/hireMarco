# FabFilter Pro-Q 3 (version 3.23 installed; claims R-AUD-0006, R-AUD-0007)

The equalizer Marco reaches for first, in mixing and in mastering. Everything
below comes from the help installed with the plug-in on this Mac, read
2026-11-02, and from Logic's own control list for it.

## The shapes, and when each is the right one

| Shape | What it does (R-AUD-0007) | When Marco chooses it |
|---|---|---|
| Bell | the parametric shape, "probably the most versatile of them all" | a tonal move or a resonance: one region up or down, width by Q |
| Notch | "to cut a small section of the spectrum" | a pure ring or a hum that must go entirely; no gain, width by Q and slope |
| Low Cut | "to cut all sound below the filter frequency" | rumble under the music, the bottom of a vocal or a hat; the slope sets how hard |
| High Cut | "to cut all sound above the filter frequency" | hiss or fizz above the music; rarely on a master |
| Low Shelf | "to boost or attenuate low frequencies" | the whole bottom up or down; a broad weight move |
| High Shelf | "to boost or attenuate high frequencies" | the whole top up or down; air or presence as one move |
| Tilt Shelf | "to tilt the spectrum around a certain frequency" | the whole balance in one move, brighter or darker around a pivot |
| Flat Tilt | "to tilt the spectrum using a flat curve, around a certain frequency" | the same tilt when the pivot region must stay as it is |
| Band Pass | "to isolate a section of the spectrum" | listening and effects only; not a corrective or tonal move |

Slope: 6 to 96 dB per octave on every shape, Brickwall on the two cuts. A
narrow slope on a Bell or Notch makes a surgical cut; a 6 dB per octave Low
Cut is a gentle lean, a 24 dB per octave one a wall.

## The dynamic band (R-AUD-0006)

A Bell or Shelf band made dynamic moves its gain with the level of its own
band-limited input: a negative dynamic range compresses the region (the cut
happens only when the region crosses the threshold), a positive one expands
it. The threshold is automatic by default (it follows the band's own level)
or set by hand with the trigger level shown; a soft knee starts the move a
little under the threshold; attack, release and knee are program dependent.
This is the right tool when the problem comes and goes: a sibilant hit, a
hat too loud on its hits, a note that rings only when it is struck. A static
band is still the first choice when the problem is always there. Not
available in Linear Phase mode at the two highest resolutions.

## The controls as Logic lists them (observed 2026-11-02)

Per band N (1 to 24): `Band N Used`, `Band N Enabled`, `Band N Frequency`
(the plug-in prints Hz; its own field also accepts a note name, "A4" or
"C#2+13"), `Band N Gain` (dB, -30 to +30), `Band N Q` (1 is the default
bandwidth; higher is narrower), `Band N Dynamic Range` (dB, -30 to +30;
negative compresses), `Band N Dynamics Enabled`, `Band N Threshold`, `Band N
External Side Chain`, `Band N Solo`, and a second, older name set (`Band N
Freq`, `Range`, `Attack`, `Release`, `SC Mode`, `SC Source`). The shape and
the slope are not in Logic's control list for this version: they are set in
the plug-in's own window or by a saved preset, and a new band is a Bell.
Global: Processing Mode (Zero Latency, Natural Phase, Linear Phase), Output
Gain, Output Pan, Auto Gain, Gain Scale.

## Units Marco reasons in

Frequency in Hz and as a note (254 Hz is B3, a semitone under the C4 a key
of C lands on); gain in dB in half-dB steps on a master and whole dB on a
take; Q as a width (0.7 broad, 1 default, 4 to 12 narrow, higher a notch);
dynamic range in dB with the same sign as the cut it should make.
