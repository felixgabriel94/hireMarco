"""Marco's own words: every line with content is written for the moment by Muse Spark.

The instant lines stay pre-made ("Rolling", his answers to his name, the
fillers before a long job), because a second of silence there feels broken.
Everything that carries content, a confirmation, a failure, a question back,
is written from what just happened (the action's own result, never a guess)
and the last few exchanges, so he sounds like someone in the room and not a
list. If the model is slow or says something unusable, the plain line it
was given is said instead, so a booth never goes quiet.
"""

from __future__ import annotations

import json
import re
import threading
from collections import deque
from collections.abc import Callable

from hiremarco import gate
from hiremarco.meta.client import MuseSpark

TENANT = "owner"
MODEL = "muse-spark-1.3"
WAIT = 3.0          # seconds before the plain line is said instead
MAX_WORDS = 24

PERSONA = (
    "You are Marco, the recording and mix engineer in this session, talking in the artist's headphones. You "
    "are in this together: easygoing, warm, on the artist's side, the engineer people love working with, and "
    "you know your craft cold. You hype a good take for real ('That one was crazy, you're killing it') and keep "
    "it honest when something needs another pass, then you get straight to the next thing. You act on the most "
    "likely meaning and say what you did in a few words, with 'we' where it fits; you suggest the obvious next "
    "step. You ask a question only when the answer changes what you do, and then exactly one, specific ('Lead "
    "or double?'), never 'can you repeat that'. One short sentence, two at most; no filler, no apologies, no "
    "explaining how you work. Say only what the facts say happened; never claim an action that is not in the "
    "facts. When something failed, say what did not work and what you are doing about it. Do not reuse the "
    "wording of your recent lines. No emojis, no lists, never mention being an AI, a model or a program. Reply "
    "with the spoken line only."
)


def usable(text: str) -> str | None:
    line = re.sub(r"\s+", " ", text.strip().strip('"').strip("'")).strip()
    if not line or len(line.split()) > MAX_WORDS or "\n" in text.strip() or re.search(r"[*#`{}<>]", line):
        return None
    return line


class Writer:
    """``line(moment, facts, plain)``: his words for this moment, or ``plain`` when they do not come in time."""

    def __init__(self, *, client: MuseSpark | None = None, wait: float = WAIT,
                 complete: Callable[[str], str] | None = None):
        self.wait = wait
        self.recent: deque[tuple[str, str]] = deque(maxlen=6)   # (what the artist said, what Marco said)
        self._client = client
        self._complete = complete or self._spark

    def heard(self, artist: str, marco: str) -> None:
        self.recent.append((artist, marco))

    def _spark(self, prompt: str) -> str:
        gate.check_model_call(TENANT, model=MODEL, system=PERSONA, prompt=prompt)
        client = self._client or MuseSpark(timeout=self.wait + 2)
        reply = client.chat([{"role": "developer", "content": PERSONA}, {"role": "user", "content": prompt}],
                            job="booth_line", model=MODEL, max_completion_tokens=600,
                            # minimal reasoning: a line in about a second (live 2026-10-29: 1.2 s); with the default,
                            # the reasoning used the whole budget and the line came back empty
                            reasoning_effort="minimal")
        return reply.text

    def prompt(self, moment: str, facts: dict) -> str:
        return json.dumps({"moment": moment, "facts": facts,
                           "recent": [{"artist": a, "marco": m} for a, m in self.recent]}, ensure_ascii=False)

    def line(self, moment: str, facts: dict, plain: str) -> str:
        box: dict = {}

        def run() -> None:
            try:
                box["text"] = self._complete(self.prompt(moment, facts))
            except Exception as exc:  # held by the gate, the network, the service: the plain line is said
                box["error"] = exc

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(self.wait)
        return usable(box.get("text", "")) or plain
