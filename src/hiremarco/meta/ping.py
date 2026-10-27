"""Round-trip one prompt through Muse Spark and show the cost.

    uv run python -m hiremarco.meta.ping "Say hello in five words."
"""

from __future__ import annotations

import sys

from hiremarco.meta.client import MuseSpark


def main(argv: list[str]) -> int:
    prompt = " ".join(argv) or "Reply with the single word: ready."
    client = MuseSpark()
    reply = client.ask(prompt, job="ping", max_completion_tokens=60)
    print(reply.text.strip())
    print(
        f"[{reply.model}] {reply.prompt_tokens} in / {reply.completion_tokens} out "
        f"({reply.cached_tokens} cached), {reply.cost_usd:.6f} USD, {reply.duration_ms} ms"
    )
    print(client.joblog.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
