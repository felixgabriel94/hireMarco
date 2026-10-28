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

import os
from pathlib import Path

from hiremarco import gate
from hiremarco.meta.client import MuseSpark, Reply

TENANT = "owner"
PERSONA_FILES = ("SOUL.md", "voice.md", "contract.md")
PUBLIC_PERSONA = (
    "You are Marco, Felix's personal assistant. Felix is a singer and producer in Miami. "
    "You are direct, warm and brief: one or two short sentences unless he asks for more. "
    "You never claim to be human, and you never say you did something you have not done."
)


def private_persona_on() -> bool:
    return bool(os.environ.get("HIREMARCO_PERSONA_DIR"))


def persona() -> str:
    folder = os.environ.get("HIREMARCO_PERSONA_DIR")
    if not folder:
        return PUBLIC_PERSONA
    parts = []
    for name in PERSONA_FILES:
        path = Path(folder) / name
        if path.is_file():
            parts.append(path.read_text())
    return "\n\n".join(parts) if parts else PUBLIC_PERSONA


class Marco:
    def __init__(self, client: MuseSpark | None = None):
        self.client = client or MuseSpark()

    def answer(self, text: str, *, job: str = "answer", max_completion_tokens: int = 200) -> Reply:
        if private_persona_on() and self.client.model.endswith("-contributor"):
            raise gate.Refused("the private persona never goes to a contributor model")
        system = persona()
        gate.check_model_call(TENANT, model=self.client.model, system=system, prompt=text, joblog=self.client.joblog)
        return self.client.ask(text, developer=system, job=job, max_completion_tokens=max_completion_tokens)
