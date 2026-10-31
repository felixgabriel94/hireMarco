"""Felix's look from his mood board (Owner 2026-10-30): pictures in batches, one pull-together, facts marked."""

import json

import httpx

from hiremarco import gate
from hiremarco.joblog import JobLog
from hiremarco.look import BATCH, MARK, keep_look, run
from hiremarco.meta.client import MuseSpark
from hiremarco.whatsapp.facts import known


def test_the_board_is_read_in_batches_and_kept_as_marked_facts(tmp_path):
    folder = tmp_path / "board"
    folder.mkdir()
    for i in range(BATCH + 3):
        (folder / f"{i:02d}.jpg").write_bytes(b"\xff\xd8jpeg")
    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        name = body["response_format"]["json_schema"]["name"]
        content = {"notes": ["washed black denim", "cream knit"]} if name == "notes" else \
            {"look": ["You lean toward washed black and cream.", "You like loose knits over fitted denim."]}
        return httpx.Response(200, json={"model": "muse-spark-1.3", "usage": {},
                                         "choices": [{"message": {"content": json.dumps(content)}}]})

    client = MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=httpx.MockTransport(respond))
    conn = gate.connect(":memory:")
    line = run(folder, "https://www.cosmos.so/fega1/moodboard", client=client, conn=conn)
    assert line == f"{BATCH + 3} pictures, 2 lines of his look, 3 new facts"
    images = [sum(1 for part in c["messages"][1]["content"] if part.get("type") == "image_url")
              for c in calls[:2]]
    assert images == [BATCH, 3] and len(calls) == 3
    facts = [t for _, t in known(conn)]
    assert facts[0] == f"{MARK}: You lean toward washed black and cream"         # kept without its full stop
    assert facts[-1] == "Your mood board is https://www.cosmos.so/fega1/moodboard"
    assert keep_look(conn, ["You lean toward washed black and cream."], "https://x") == 1   # only the new link
