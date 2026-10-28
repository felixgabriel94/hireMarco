"""The critic: a second model pass before anything that cannot be taken back.

It runs on Muse Wonder, Meta's top-tier model: everyday work stays on Muse
Spark, and only actions that cannot be taken back pay for the stronger
judge. It reads RULES.md and one plain description of the action, and
answers APPROVE or HOLD with a short reason. Anything else, or any error, is a hold:
the critic fails closed.
"""

from __future__ import annotations

from pathlib import Path

from hiremarco import gate, rules
from hiremarco.meta.client import MuseSpark

TENANT = "owner"
CRITIC_MODEL = "muse-wonder-1.0"

INSTRUCTIONS = """You are the critic for Marco, a personal assistant. Marco wants to take one action that cannot be taken back. Check it against the rules below and against plain sense: is it what the Owner asked for, is the recipient right, is anything in it false, private or careless?

Answer on one line, exactly one of:
APPROVE: <reason in under 12 words>
HOLD: <reason in under 12 words>

Rules:
"""


def parse(text: str) -> tuple[bool, str]:
    line = (text or "").strip().splitlines()[0].strip() if (text or "").strip() else ""
    head, _, reason = line.partition(":")
    head = head.strip().upper()
    if head == "APPROVE":
        return True, reason.strip() or "approved"
    if head == "HOLD":
        return False, reason.strip() or "held"
    return False, "the critic's answer was unreadable"


class Critic:
    def __init__(self, client: MuseSpark | None = None, rules_path: Path | None = None, model: str = CRITIC_MODEL):
        self.client = client
        self.rules_path = rules_path or rules.RULES_PATH
        self.model = model

    def __call__(self, description: str) -> tuple[bool, str]:
        system = INSTRUCTIONS + self.rules_path.read_text()
        client = self.client or MuseSpark()
        gate.check_model_call(TENANT, model=self.model, system=system, prompt=description, joblog=client.joblog)
        reply = client.ask(description, developer=system, job="critic", model=self.model, max_completion_tokens=40)
        return parse(reply.text)
