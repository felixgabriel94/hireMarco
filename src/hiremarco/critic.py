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


def verdict_line(text: str) -> tuple[str, str]:
    """The critic's verdict for the live view: a hold reads as held."""
    approved, reason = parse(text)
    return ("ok", f"Approved. {reason}") if approved else ("refused", f"Held. {reason}")


class Critic:
    def __init__(self, client: MuseSpark | None = None, rules_path: Path | None = None, model: str = CRITIC_MODEL,
                 effort: str = "low", tokens: int = 600, timeout: float = 60.0):
        """``effort`` low for the sends that happen all day; ``max`` where the critic judges a mix or a master plan
        (Owner 2026-11-02: deep thinking on every mix and master decision), with ``tokens`` and ``timeout`` raised
        to match."""
        self.client = client
        self.rules_path = rules_path or rules.RULES_PATH
        self.model = model
        self.effort, self.tokens, self.timeout = effort, tokens, timeout

    def __call__(self, description: str) -> tuple[bool, str]:
        system = INSTRUCTIONS + self.rules_path.read_text()
        client = self.client or MuseSpark(timeout=self.timeout)
        gate.check_model_call(TENANT, model=self.model, system=system, prompt=description, joblog=client.joblog)
        # Muse Wonder reasons before it answers: at 40 tokens (live 2026-10-31) 38 went to reasoning, the answer was
        # empty and the first call was held as unreadable. Room for both, and still a hold on anything unreadable.
        reply = client.ask(description, developer=system, job="critic", model=self.model,
                           max_completion_tokens=self.tokens, reasoning_effort=self.effort, summarize=verdict_line)
        if not reply.text.strip() and reply.finish_reason == "length":
            return False, "the critic ran out of room before answering"
        return parse(reply.text)
