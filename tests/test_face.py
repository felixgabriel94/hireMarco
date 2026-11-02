"""The plug-in's face: a license notice read off its window, and what the job does with one."""

import json

import httpx

from hiremarco.joblog import JobLog
from hiremarco.meta.client import MuseSpark
from hiremarco.studio import face


def spark(tmp_path, content, seen):
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "muse-spark-1.3", "choices": [{"message": {"content": content},
                              "finish_reason": "stop"}], "usage": {"prompt_tokens": 900, "completion_tokens": 40}})

    return MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=httpx.MockTransport(handler))


def test_a_notice_on_the_face_reads_as_unlicensed(tmp_path):
    seen = []
    reply = json.dumps({"licensed": False, "notice": "SUBSCRIPTION NOT ACTIVE", "plugin": "Shadow Hills Mastering Compressor"})
    f = face.look("Stereo Out", client=spark(tmp_path, reply, seen), shoot=lambda name: b"\x89PNG fake")
    assert not f.licensed and f.notice == "SUBSCRIPTION NOT ACTIVE"
    sent = seen[0]
    assert sent["model"] == "muse-spark-1.3"
    assert sent["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_a_plain_face_reads_as_licensed(tmp_path):
    reply = json.dumps({"licensed": True, "notice": "", "plugin": "Pro-L 2"})
    f = face.look(client=spark(tmp_path, reply, []), shoot=lambda name: b"png")
    assert f.licensed and f.notice == "" and f.plugin == "Pro-L 2"


def test_an_unreadable_face_is_no_reading_not_a_stop(tmp_path, monkeypatch):
    from hiremarco import config

    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    said = []
    assert face.look(client=spark(tmp_path, "", []), shoot=lambda name: b"png", log=said.append) is None
    assert said and "could not be read" in said[0] and "unreadable" in said[0]
    assert any(p.suffix == ".png" for p in (tmp_path / "capture").iterdir())


def test_a_capture_that_fails_is_no_reading_either(tmp_path):
    def boom(name):
        raise RuntimeError("no window named FG Master")

    assert face.look("FG Master", client=spark(tmp_path, "{}", []), shoot=boom) is None
