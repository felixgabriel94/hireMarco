"""Marco's voice: one Muse Spark call, with his persona, through the gate.

The full persona is private and never in this repository. When
``HIREMARCO_PERSONA_DIR`` points at a private folder, Marco reads exactly
three files from it (SOUL.md, voice.md, contract.md); anything else there is
ignored. Without it he runs on the short public line below.

The private persona goes only to Standard-mode models. Meta's pricing page
(read 2026-10-28) says Standard-mode content is not used to train Meta
models, while the ``-contributor`` models trade that for lower prices, so a
contributor model never sees it.
"""

from __future__ import annotations

import re
from pathlib import Path

from hiremarco import config, gate
from hiremarco.meta.client import MuseSpark, Reply

TENANT = "owner"
PERSONA_FILES = ("SOUL.md", "voice.md", "contract.md")
PUBLIC_PERSONA = (
    "You are Marco, Felix's personal assistant. Felix is a singer and producer in Miami. "
    "You are direct, warm and brief: one or two short sentences unless he asks for more. "
    "You never claim to be human, and you never say you did something you have not done."
)


def private_persona_on() -> bool:
    return bool(config.get("HIREMARCO_PERSONA_DIR"))


def persona() -> str:
    """The three persona files, their comment blocks (notes to the people who edit them) removed."""
    folder = config.get("HIREMARCO_PERSONA_DIR")
    if not folder:
        return PUBLIC_PERSONA
    parts = []
    for name in PERSONA_FILES:
        path = Path(folder) / name
        if path.is_file():
            parts.append(re.sub(r"<!--.*?-->", "", path.read_text(), flags=re.S).strip())
    return "\n\n".join(p for p in parts if p) or PUBLIC_PERSONA


class Marco:
    def __init__(self, client: MuseSpark | None = None):
        self.client = client or MuseSpark()

    def answer(self, text: str, *, job: str = "answer", max_completion_tokens: int = 800,
               reasoning_effort: str = "low", instructions: str = "") -> Reply:
        """Marco's reply. The budget counts his thinking too: at 200 tokens he thought it all away and the reply
        came back empty (live 2026-10-30, a WhatsApp "hey"), so chat replies think low with room to spare."""
        if private_persona_on() and self.client.model.endswith("-contributor"):
            raise gate.Refused("the private persona never goes to a contributor model")
        system = persona() + (f"\n\n{instructions}" if instructions else "")
        gate.check_model_call(TENANT, model=self.client.model, system=system, prompt=text, joblog=self.client.joblog)
        return self.client.ask(text, developer=system, job=job, max_completion_tokens=max_completion_tokens,
                               reasoning_effort=reasoning_effort)

    def converse(self, history: list[dict], text: str, *, instructions: str = "", job: str = "converse",
                 response_format: dict | None = None, max_completion_tokens: int = 1500,
                 reasoning_effort: str = "low") -> Reply:
        """Marco with the conversation so far (``history``: user and assistant turns, oldest first) before ``text``,
        through the same gate and persona rule as ``answer``."""
        if private_persona_on() and self.client.model.endswith("-contributor"):
            raise gate.Refused("the private persona never goes to a contributor model")
        system = persona() + (f"\n\n{instructions}" if instructions else "")
        gate.check_model_call(TENANT, model=self.client.model, system=system,
                              prompt="\n".join([*(h["content"] for h in history), text]), joblog=self.client.joblog)
        messages = [{"role": "developer", "content": system}, *history, {"role": "user", "content": text}]
        return self.client.chat(messages, job=job, max_completion_tokens=max_completion_tokens,
                                response_format=response_format, reasoning_effort=reasoning_effort)
