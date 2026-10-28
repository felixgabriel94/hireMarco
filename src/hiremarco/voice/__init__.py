"""Marco's voice: ElevenLabs text to speech, talkback in the booth, the voice note.

Talkback plays into the Owner's headphones between takes, never over one, and
keeps every line it spoke as a timestamped WAV for the film. The voice note is
one WhatsApp voice message, prepared ahead and sent on the Owner's Return.
"""

from .talkback import Talkback, TakeRolling
from .tts import RATE, Speech, synthesize
from .voicenote import VoiceNote, prepare_voice_note

__all__ = ["RATE", "Speech", "Talkback", "TakeRolling", "VoiceNote", "prepare_voice_note", "synthesize"]
