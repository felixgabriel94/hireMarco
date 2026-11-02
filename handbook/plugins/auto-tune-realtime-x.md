# UAD Auto-Tune Realtime X (claim R-AUD-0019)

The tuner on every part of the artist's vocal chain (taste pass, 2026-11-02:
Retune Speed 10 on the lead, 6 on the BGVs, 12 on the ad-libs, 8 on the robo;
Detune 50). From the manual installed with UAD on this Mac, read 2026-11-02.

## How Marco reasons with it

- **Key and Scale**: the song's key as Marco read it from the audio
  (mix/key.py, with its confidence), confirmed against the artist's word;
  Chromatic only when neither is known, because a chromatic scale tunes a
  slide to the wrong note as happily as the right one.
- **Retune Speed** (ms): the lead between 10 and 50 for a natural voice; lower
  for the tight, iconic effect the artist asks for by name; higher for a
  part that carries its own vibrato. The artist's 10 on the lead and 6 on
  the BGVs are his sound, kept unless he asks.
- **Flex-Tune**: up when the take has gestures worth keeping (a scoop into a
  note); 0 when every note must land.
- **Humanize**: raised when sustained notes read as static at the chosen
  speed; set after the speed, as the maker says.
- **Detune**: the reference pitch; the artist's 50 cents is a deliberate
  choice and stays unless the key read shows the beat sits at 440.
- **Classic Mode**: the Auto-Tune 5 sound, brighter with a harder attack
  between notes; Flex-Tune is off in it.

## Verify

The take's pitch track before and after (studio/pitch.py): the notes land on
the scale, the gestures the setting meant to keep are still there, no
flutter between adjacent notes.
