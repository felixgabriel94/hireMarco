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
