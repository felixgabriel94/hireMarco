"""Marco's own words: every line with content is written for the moment by Muse Spark.

The instant lines stay pre-made ("Rolling", his answers to his name), because
a second of silence there feels broken. While he thinks he says nothing: no
"one sec", no sound; he speaks when his line is ready (Owner 2026-11-01).
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
from hiremarco.voice.tts import speakable

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
    "explaining how you work. Never say hmm, mm, uh or um, and no thinking sounds of any kind; never speak while the "
    "artist is still talking; wait until he has finished. Never curt or bossy: no bare 'go ahead' or orders; you sound glad to be there. Say only what the facts say happened; never claim an action that is not in the "
    "facts. When something failed, say what did not work and what you are doing about it. Do not reuse the "
    "wording of your recent lines. No emojis, no lists, never mention being an AI, a model or a program. Reply "
    "with the spoken line only. The artist is FEGA: if you say his name, it is FEGA."
)


def usable(text: str) -> str | None:
    line = re.sub(r"\s+", " ", text.strip().strip('"').strip("'")).strip()
    if not speakable(line) or len(line.split()) > MAX_WORDS or "\n" in text.strip() or re.search(r"[*#`{}<>]", line):
        return None
    return line


HOW_TO_SAY = re.compile(r";\s*(?:say|ask|tell|answer|offer|give|list|sign off|confirm)\b.*$", re.I | re.S)
FOR_THE_ROOM = [(r"\bthe artist's\b", "FEGA's"), (r"\bthe artist\b", "FEGA"), (r"\bhis\b", "FEGA's"),
                (r"\bhim\b", "FEGA"), (r"\bhe's\b", "FEGA's"), (r"\bhe\b", "FEGA"), (r"\byou'll\b", "I'll"),
                (r"\byou're\b", "I'm"), (r"\byou've\b", "I've"), (r"\byour\b", "my"), (r"\byou\b", "I")]


def thought(moment: str) -> str:
    """What the Live trace shows for a booth line: his own thought about the moment, never the words he says to
    the artist (Owner 2026-11-04: the trace is for the audience, Marco thinking out loud, never "with you").
    "every track in his session is labeled; say ..." -> "Every track in FEGA's session is labeled."."""
    said = HOW_TO_SAY.sub("", moment or "").strip(" ;,.")
    for pattern, word in FOR_THE_ROOM:
        said = re.sub(pattern, word, said, flags=re.I)
    if not said:
        raise ValueError("no moment to think about")
    return said[0].upper() + said[1:] + "."


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
        try:
            moment = json.loads(prompt).get("moment", "")
        except (ValueError, AttributeError):
            moment = ""
        reply = client.chat([{"role": "developer", "content": PERSONA}, {"role": "user", "content": prompt}],
                            job="booth_line", model=MODEL, max_completion_tokens=600,
                            summarize=lambda text: thought(moment),   # the trace shows his thought, not his line
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
