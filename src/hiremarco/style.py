"""How Marco writes to the artist on WhatsApp (Owner 2026-10-30): lowercase, the way artists text.

Links keep their exact letters (a live-view code is case-sensitive), and an
all-caps word stays as it is (SZA, BPM, LUFS). Song titles go lowercase too.
"""

from __future__ import annotations

import re

URL = re.compile(r"https?://\S+")
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def casual(text: str) -> str:
    def lower(part: str) -> str:
        return WORD.sub(lambda m: m.group(0) if len(m.group(0)) > 1 and m.group(0).isupper() else m.group(0).lower(),
                        part)

    out, last = [], 0
    for m in URL.finditer(text or ""):
        out += [lower(text[last:m.start()]), m.group(0)]
        last = m.end()
    out.append(lower((text or "")[last:]))
    return "".join(out)


# Owner 2026-10-31: Marco never shows the client what is under the hood. A text that would name a part of the
# system, a tool, a model or an error goes out as a plain line instead; the raw text goes to the log only.
INTERNAL = re.compile(
    r"\b(critic|gate(?! code)|relay|send switch|idempotenc\w*|refused|webhook|tunnel|elevenlabs|twilio|"
    r"muse (spark|wonder)|model call|traceback|exception|callsid|conv_\w+|end_call|voicemail_detection|skip_turn|"
    r"rules\.md|(the|call|a) brief)\b|\bhttp \d{3}\b", re.I)
PLAIN = "Something didn't go through on my side just now. I'm on it."


def plain(text: str) -> tuple[str, str | None]:
    """The text as it may go to the client, and the raw text when it had to be replaced (for the log only)."""
    return (PLAIN, text) if INTERNAL.search(text or "") else (text, None)
