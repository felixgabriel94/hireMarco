"""Harmony voices from a sung line: the music math, in the song's key.

Owner 2026-10-31: he records a harmony line and asks "what's the second voice?", then the third, then "what could be
a fifth?", and Marco plays each one as a guide in his ears and names its notes, so a big stack never gets lost.
Every voice moves in the key's own scale steps (diatonic), the way harmonies are built: a third is two scale steps,
a fifth four, a sixth five, an octave seven. "The next voice" stacks a third above the highest voice so far, so a
line grows into a chord (root, third, fifth, then the octave); "below" builds downward the same way.
"""

from __future__ import annotations

import re
from dataclasses import replace

from hiremarco.studio.pitch import Note, midi_name, parse_key

STEPS = {"second": 1, "third": 2, "fourth": 3, "fifth": 4, "sixth": 5, "seventh": 6, "octave": 7}
NUMBERS = {"2nd": "second", "3rd": "third", "4th": "fourth", "5th": "fifth", "6th": "sixth", "7th": "seventh",
           "8th": "octave", "eighth": "octave"}


def shift(run: list[Note], key: str, steps: int) -> list[Note]:
    """The line moved ``steps`` scale steps up (or down when negative) inside ``key``; the sung rhythm kept."""
    tonic, scale = parse_key(key)
    out = []
    for n in run:
        degree = (n.target - tonic) % 12
        if degree not in scale:  # off the key: the nearest scale note below carries the step
            degree = max(d for d in scale if d <= degree) if any(d <= degree for d in scale) else scale[0]
        octave, index = divmod(scale.index(degree) + steps, len(scale))
        base = n.target - ((n.target - tonic) % 12) + scale[0]
        target = base + 12 * octave + scale[index] - scale[0]
        out.append(replace(n, midi=float(target), target=target))
    return out


def ask(said: str) -> tuple[int, bool]:
    """What he asked for, as (scale steps, from the highest or lowest voice so far). "The third above" is (2, False):
    from the line he sang. "The next voice" or "the second voice" is (2, True): a third over the stack's top.
    "Below" or "under" makes it negative."""
    words = said.lower()
    for short, word in NUMBERS.items():
        words = re.sub(rf"\b{short}\b", word, words)
    down = bool(re.search(r"\b(?:below|under|beneath|lower|down)\b", words))
    stacked = bool(re.search(r"\b(?:next|another|second voice|third voice|fourth voice|fifth voice|voice)\b", words))
    steps = 2
    for word, n in STEPS.items():
        if re.search(rf"\b{word}\b(?! voice)", words):
            steps = n
            break
    return (-steps if down else steps), stacked


def names(run: list[Note]) -> str:
    """The notes as he'd read them, repeats folded: "E F# G"."""
    out: list[str] = []
    for n in run:
        name = midi_name(n.target).rstrip("-0123456789")  # the note, not its octave: "G", not "G4"
        if not out or out[-1] != name:
            out.append(name)
    return " ".join(out)


class Stack:
    """The voices built so far over one sung line, so "the next voice" knows where the top is."""

    def __init__(self, line: list[Note], key: str):
        self.key = key
        self.voices: list[list[Note]] = [line]

    def add(self, said: str) -> list[Note]:
        steps, stacked = ask(said)
        if stacked:
            edge = max(self.voices, key=_middle) if steps > 0 else min(self.voices, key=_middle)
        else:
            edge = self.voices[0]
        voice = shift(edge, self.key, steps)
        self.voices.append(voice)
        return voice


def _middle(run: list[Note]) -> float:
    return sum(n.target for n in run) / max(1, len(run))
