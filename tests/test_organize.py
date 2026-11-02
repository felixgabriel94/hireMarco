"""Organizing a session: the survey read as bars, the plan from the brain, the renames on go."""

import json

import httpx

from hiremarco.joblog import JobLog
from hiremarco.meta.client import MuseSpark
from hiremarco.studio import organize

RAW = {"headers": [{"desc": "Track 1 “BEAT”", "triangle": "0"}, {"desc": "Track 4 “FEGA”", "triangle": "1"},
                   {"desc": "Track 6 “intro lead”", "triangle": None},
                   {"desc": "Track 12 “002-MY VOCAL CHAIN!”", "triangle": None}, {"desc": "Control Bar"}],
       "lanes": [{"desc": "Track 1 “BEAT”", "regions": [["REtrosito", 568, 58]]},
                 {"desc": "Track 6 “intro lead”", "regions": [["002-MY VOCAL CHAIN", 640, 8], ["002-MY VOCAL CHAIN", 583, 9]]},
                 {"desc": "Track 12 “002-MY VOCAL CHAIN!”", "regions": [["002-MY VOCAL CHAIN", 700, 8]]}],
       "thumb_x": 563}
RAW_65 = {"thumb_x": 563 + 64 * 7.28125}


def test_the_survey_reads_screen_x_as_bars_and_stacks_by_their_triangle():
    lay = organize.parse_survey(RAW, RAW_65, 1, 65)
    assert [t.number for t in lay.tracks] == [1, 4, 6, 12] and round(lay.px_per_bar, 3) == 7.281
    beat, fega, intro, chain = lay.tracks
    assert beat.stack == "closed" and fega.stack == "open" and intro.stack == ""
    assert round(beat.regions[0].bar, 1) == 1.7 and round(beat.regions[0].bars, 1) == 8.0
    assert [round(r.bar, 1) for r in intro.regions] == [3.7, 11.6]          # sorted by bar
    assert lay.compact()[2] == {"number": 6, "name": "intro lead", "stack": "no", "regions": 2,
                                "each": [["002-MY VOCAL CHAIN", 3.7, 1.2], ["002-MY VOCAL CHAIN", 11.6, 1.1]]}
    many = organize.Track(14, "x", "", [organize.Region("a#1", 20.8 + 2 * i, 1.5) for i in range(4)]
                          + [organize.Region("a#2", 46.7 + 2 * i, 1.5) for i in range(3)])
    assert organize.Survey([many], 7.3, 563).compact()[0] == {"number": 14, "name": "x", "stack": "no", "regions": 7,
                                                              "spans": [[20.8, 28.3], [46.7, 52.2]], "names": ["a"]}


def test_survey_jumps_to_two_bars_and_reads_twice():
    went, reads = [], iter([RAW, RAW_65])
    lay = organize.survey(read=lambda: next(reads), go=lambda b: went.append(b))
    assert went == [1, 65] and len(lay.tracks) == 4


def wonder(tmp_path, content, seen):
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "muse-wonder-1.0", "choices": [{"message": {"content": content},
                              "finish_reason": "stop"}], "usage": {"prompt_tokens": 3000, "completion_tokens": 300}})

    return MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=httpx.MockTransport(handler))


def test_the_plan_names_every_track_and_keeps_the_ones_the_brain_skipped(tmp_path):
    lay = organize.parse_survey(RAW, RAW_65, 1, 65)
    seen = []
    reply = json.dumps({"sections": [{"name": "Intro", "start_bar": 1, "end_bar": 18, "evidence": "the intro lead sits at 3.7 to 12.7"}],
                        "tracks": [{"number": 6, "current": "intro lead", "proposed": "Lead Intro", "color": "blue", "role": "lead",
                                    "flag": "", "reason": "regions at 3.7 and 11.6, both in the intro"},
                                   {"number": 12, "current": "002-MY VOCAL CHAIN!", "proposed": "Lead Chorus 2", "color": "blue",
                                    "role": "lead", "flag": "", "reason": "one region at 19.8"},
                                   {"number": 99, "current": "ghost", "proposed": "x", "color": "", "role": "", "flag": "", "reason": ""}],
                        "said": "Named the leads by section. Look at the chorus take on track 12."})
    plan = organize.propose(lay, client=wonder(tmp_path, reply, seen))
    assert [t["number"] for t in plan.tracks] == [1, 4, 6, 12]                        # in the session's order, no ghost
    assert plan.tracks[2]["proposed"] == "Lead Intro" and plan.tracks[0]["flag"] == "not answered"
    assert [t["number"] for t in plan.changes()] == [6, 12] and plan.sections[0]["name"] == "Intro"
    body = seen[0]
    assert body["model"] == "muse-wonder-1.0" and body["reasoning_effort"] == organize.EFFORT
    sent = json.loads(body["messages"][-1]["content"])
    assert sent["standard"]["colors"]["lead"] == "blue" and sent["session"][0]["stack"] == "closed"
    assert "| 6 | intro lead | Lead Intro |" in plan.table()


def test_apply_renames_each_change_and_reads_the_names_back():
    plan = organize.Plan([], [{"number": 6, "current": "intro lead", "proposed": "Lead Intro", "color": "", "role": "", "flag": "", "reason": ""},
                              {"number": 1, "current": "BEAT", "proposed": "BEAT", "color": "", "role": "", "flag": "", "reason": ""}], "")
    names, log = {6: "intro lead", 1: "BEAT"}, []
    done = organize.apply(plan, select=lambda name, n: log.append(("select", name, n)),
                          rename=lambda new: names.__setitem__(6, new) or "renamed", read_names=lambda: dict(names),
                          log=lambda s: None)
    assert done == [(6, "intro lead", "Lead Intro")] and log == [("select", "intro lead", 6)]


def test_names_read_back_by_logics_track_number_not_the_row():
    listing = "1\tTrack 1 \u201cBEAT\u201d\t13\n2\tTrack 4 \u201cVOCALS\u201d\t0\n3\tTrack 6 \u201cLead Vox 1\u201d, mute\t19\n"
    assert organize.names_by_track_number(listing) == {1: "BEAT", 4: "VOCALS", 6: "Lead Vox 1"}
