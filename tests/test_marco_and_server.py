import httpx

from hiremarco import config, gate, marco
from hiremarco.joblog import JobLog
from hiremarco.meta.client import MuseSpark
from hiremarco.server import handle
from hiremarco.whatsapp import Inbound, WhatsApp
from hiremarco.whatsapp.client import record_inbound

OWNER = "13055550100"


def muse(tmp_path, text="Here, Felix."):
    def handler(request):
        return httpx.Response(200, json={
            "model": "muse-spark-1.3",
            "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 4},
        })

    return MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=httpx.MockTransport(handler))


def test_persona_reads_only_the_three_files(tmp_path, monkeypatch):
    monkeypatch.delenv("HIREMARCO_PERSONA_DIR", raising=False)
    assert marco.persona() == marco.PUBLIC_PERSONA
    (tmp_path / "SOUL.md").write_text("soul")
    (tmp_path / "voice.md").write_text("voice")
    (tmp_path / "memory.md").write_text("private memory")
    monkeypatch.setenv("HIREMARCO_PERSONA_DIR", str(tmp_path))
    text = marco.persona()
    assert "soul" in text and "voice" in text and "private memory" not in text


def test_answer_passes_the_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    gate.set_kill_switch(True)
    try:
        marco.Marco(muse(tmp_path)).answer("hi")
        raised = False
    except gate.Refused:
        raised = True
    gate.set_kill_switch(False)
    assert raised
    assert marco.Marco(muse(tmp_path)).answer("hi").text == "Here, Felix."


def test_handle_reads_types_answers_and_replies(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    monkeypatch.setenv("OWNER_WHATSAPP", OWNER)
    rules_path = tmp_path / "RULES.md"
    rules_path.write_text(f"send: whatsapp -> {OWNER} ; the Owner's own chat ; until 2099-01-01\n")
    sent = []
    transport = httpx.MockTransport(lambda r: (sent.append(r.content), httpx.Response(200, json={"messages": [{"id": "wamid.o"}]}))[1])
    wa = WhatsApp(token="t", phone_number_id="1", conn=gate.connect(":memory:"), transport=transport, rules_path=rules_path)
    record_inbound(wa.conn, "wamid.in", OWNER, "text")
    line = handle(Inbound(id="wamid.in", sender=OWNER, kind="text", text="Marco?"), marco=marco.Marco(muse(tmp_path)), wa=wa)
    assert line.startswith("heard: Marco? > replied > ")
    assert b'"status":"read"' in sent[0] and b"Here, Felix." in sent[1]
    # the same inbound message never gets a second reply
    again = handle(Inbound(id="wamid.in", sender=OWNER, kind="text", text="Marco?"), marco=marco.Marco(muse(tmp_path)), wa=wa)
    assert "held:" in again


def test_set_value_keeps_others_and_mode(tmp_path):
    path = tmp_path / "env"
    path.write_text("# c\nA=1\nB=\n")
    config.set_value("B", "two", path)
    config.set_value("C", "three", path)
    assert path.read_text() == "# c\nA=1\nB=two\nC=three\n"
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_private_persona_never_goes_to_a_contributor_model(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    (tmp_path / "SOUL.md").write_text("soul")
    monkeypatch.setenv("HIREMARCO_PERSONA_DIR", str(tmp_path))
    client = muse(tmp_path)
    client.model = "muse-spark-1.3-contributor"
    try:
        marco.Marco(client).answer("hi")
        raised = False
    except gate.Refused:
        raised = True
    assert raised
