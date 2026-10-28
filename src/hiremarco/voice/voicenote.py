"""The voice note: Marco's sign-off, one WhatsApp voice message.

Prepared ahead (speech made, checked, kept) so the send on the Owner's Return
is only the upload and the message. WhatsApp shows a voice message, with the
microphone and not the music icon, only for a mono Ogg file with the OPUS
codec and ``voice: true`` on the audio object (Meta's audio messages docs,
read 2026-10-28); anything else arrives as a plain audio file.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import soundfile as sf

from hiremarco.voice.talkback import capture_dir
from hiremarco.voice.tts import RATE, Speech, synthesize


@dataclass(frozen=True)
class VoiceNote:
    ogg: Path
    text: str
    seconds: float

    @classmethod
    def load(cls, ogg: Path) -> VoiceNote:
        ogg = Path(ogg)
        text = ogg.with_suffix(".txt").read_text().strip()
        info = sf.info(ogg)
        if (info.format, info.subtype, info.channels) != ("OGG", "OPUS", 1):
            raise ValueError(f"{ogg.name} is {info.format}/{info.subtype}, {info.channels} channels; "
                             "a voice note must be mono OGG/OPUS")
        return cls(ogg, text, info.duration)


def prepare_voice_note(text: str, *, speak: Callable[[str], Speech] = synthesize,
                       folder: Path | None = None) -> VoiceNote:
    speech = speak(text)
    folder = folder or capture_dir()
    folder.mkdir(parents=True, exist_ok=True)
    stem = datetime.now().astimezone().strftime("%Y-%m-%dT%H-%M-%S") + "_voice-note"
    ogg = folder / f"{stem}.ogg"
    sf.write(ogg, speech.pcm, RATE, format="OGG", subtype="OPUS")
    sf.write(folder / f"{stem}.wav", speech.pcm, RATE, subtype="PCM_16")
    ogg.with_suffix(".txt").write_text(speech.text + "\n")
    return VoiceNote.load(ogg)
