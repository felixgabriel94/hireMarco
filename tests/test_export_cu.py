import pytest

from hiremarco import gate
from hiremarco.joblog import JobLog
from hiremarco.studio.export_cu import MAX_STEPS, HandBack, Window, export_by_computer_use, vet

WINDOW = Window(0, 25, 1440, 875)
FOLDER = "Song - ready to mix"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))


def call(call_id, *actions, checks=()):
    return {"id": f"resp_{call_id}", "output": [{"type": "computer_call", "id": f"cu_{call_id}",
            "call_id": call_id, "actions": list(actions), "pending_safety_checks": list(checks),
            "status": "completed"}]}


DONE = {"id": "resp_done", "output": [{"type": "message", "content": [
    {"type": "output_text", "text": "The export has started."}]}]}


def scripted(*responses):
    sent, queue = [], list(responses)

    def post(body):
        sent.append(body)
        return queue.pop(0)

    return post, sent


def run(tmp_path, post, *, switch=True, dry_run=False, driven=None):
    rules = tmp_path / "RULES.md"
    rules.write_text("send: logic -> * ; the export dialog ; until 2099-01-01\n" if switch else "")
    driven = driven if driven is not None else []
    return export_by_computer_use(
        FOLDER, post=post, screenshot=lambda: b"\x89PNG", window=lambda: WINDOW,
        driver=driven.append, open_dialog=lambda: driven.append({"type": "open"}),
        conn=gate.connect(":memory:"), rules_path=rules, joblog=JobLog(tmp_path / "j.jsonl"),
        dry_run=dry_run, settle_s=0)


def test_clicks_through_the_dialog_and_returns_screens(tmp_path):
    post, sent = scripted(
        call("c1", {"type": "click", "button": "left", "x": 700, "y": 400}),
        call("c2", {"type": "type", "text": FOLDER}, {"type": "keypress", "keys": ["RETURN"]}),
        DONE)
    driven = []
    result = run(tmp_path, post, driven=driven)
    assert result.steps == 2 and result.final_text == "The export has started."
    assert [a["type"] for a in driven] == ["open", "click", "type", "keypress"]
    assert sent[0]["tools"] == [{"type": "computer"}]
    assert sent[0]["input"][0]["content"][1]["image_url"].startswith("data:image/png;base64,")
    follow = sent[1]
    assert follow["previous_response_id"] == "resp_c1"
    assert follow["input"][0]["type"] == "computer_call_output" and follow["input"][0]["call_id"] == "c1"
    assert follow["input"][0]["acknowledged_safety_checks"] == []


def test_dry_run_touches_nothing(tmp_path):
    post, _ = scripted(call("c1", {"type": "click", "x": 10, "y": 30}), DONE)
    driven = []
    result = run(tmp_path, post, dry_run=True, driven=driven, switch=False)
    assert driven == [] and result.actions == [{"type": "click", "x": 10, "y": 30}]


def test_without_the_logic_switch_nothing_moves(tmp_path):
    post, _ = scripted(call("c1", {"type": "click", "x": 10, "y": 30}), DONE)
    driven = []
    with pytest.raises(gate.Refused, match="no send switch for logic"):
        run(tmp_path, post, switch=False, driven=driven)
    assert driven == []


@pytest.mark.parametrize("action, why", [
    ({"type": "click", "button": "left", "x": 2000, "y": 400}, "outside Logic"),
    ({"type": "click", "button": "right", "x": 100, "y": 400}, "right click"),
    ({"type": "keypress", "keys": ["CMD", "Q"]}, "not dialog keys"),
    ({"type": "type", "text": "rm -rf ~"}, "other than the folder name"),
    ({"type": "scroll", "x": 1, "y": 30, "scroll_x": 0, "scroll_y": 5}, "not allowed"),
    ({"type": "drag", "path": [{"x": 1, "y": 30}, {"x": 9, "y": 40}]}, "not allowed"),
])
def test_the_leash(action, why):
    with pytest.raises(HandBack, match=why):
        vet(action, WINDOW, FOLDER)


def test_a_bad_action_stops_before_anything_runs(tmp_path):
    post, _ = scripted(call("c1", {"type": "click", "x": 100, "y": 400}, {"type": "keypress", "keys": ["CMD", "Q"]}))
    driven = []
    with pytest.raises(HandBack):
        run(tmp_path, post, driven=driven)
    assert [a["type"] for a in driven] == ["open", "click"]


def test_a_safety_check_is_never_acknowledged_by_code(tmp_path):
    post, sent = scripted(call("c1", {"type": "click", "x": 100, "y": 400},
                               checks=[{"id": "sc1", "code": "irreversible_action", "message": "?"}]))
    driven = []
    with pytest.raises(HandBack, match="safety check"):
        run(tmp_path, post, driven=driven)
    assert [a["type"] for a in driven] == ["open"] and len(sent) == 1


def test_step_cap(tmp_path):
    post, _ = scripted(*[call(f"c{i}", {"type": "wait"}) for i in range(MAX_STEPS + 2)])
    with pytest.raises(HandBack, match="steps"):
        run(tmp_path, post)
