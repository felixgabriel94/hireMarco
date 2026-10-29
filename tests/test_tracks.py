import pytest

from hiremarco import gate
from hiremarco.studio.tracks import NotMapped, SessionState, TrackInfo, Tracks, parse_list, track_name


def listing(n_tracks, regions_each):
    return "\n".join(f"{i}\tTrack {i} “002-MY CHAIN!”\t{regions_each}" for i in range(1, n_tracks + 1))


def rules(tmp_path):
    p = tmp_path / "RULES.md"
    p.write_text("send: logic -> * ; Logic ; until 2099-01-01\n")
    return p


def test_list_parses_names_out_of_logics_track_labels():
    tracks = parse_list(listing(2, 3) + "\nnoise")
    assert tracks == [TrackInfo(1, "002-MY CHAIN!", 3), TrackInfo(2, "002-MY CHAIN!", 3)]


def test_a_template_is_recording_and_a_developed_session_is_mixing(tmp_path):
    fresh = Tracks(run=lambda a: listing(4, 0)).scan()
    assert fresh.mode == "recording" and not fresh.developed
    busy = Tracks(run=lambda a: listing(40, 3)).scan()
    assert busy.mode == "mixing" and busy.developed


def test_names_are_numbered_from_the_second_of_a_kind():
    counts = {}
    assert [track_name(k, counts) for k in ("lead", "harmony", "harmony", "ad-lib", "lead")] == \
        ["Lead Vox", "Harmony 1", "Harmony 2", "Ad-lib 1", "Lead Vox 2"]


def test_rename_goes_through_the_gate_and_reads_back(tmp_path):
    calls = []

    def fake(args):
        calls.append(args)
        return f"renamed\t002-MY CHAIN!\t{args[1]}" if args[0] == "rename" else ""

    tracks = Tracks(run=fake, conn=gate.connect(":memory:"), rules_path=rules(tmp_path))
    assert tracks.rename("Harmony 2") == "renamed '002-MY CHAIN!' to 'Harmony 2'"
    assert calls == [["rename", "Harmony 2"]]
    with pytest.raises(gate.Refused):
        tracks.rename("   ")


def test_a_name_that_does_not_take_is_an_error(tmp_path):
    tracks = Tracks(run=lambda a: "renamed\told\tstill old", conn=gate.connect(":memory:"), rules_path=rules(tmp_path))
    with pytest.raises(RuntimeError, match="did not take"):
        tracks.rename("Lead Vox")


def test_label_names_the_track_and_notes_the_unmapped_color(tmp_path):
    tracks = Tracks(run=lambda a: f"renamed\tx\t{a[1]}", conn=gate.connect(":memory:"), rules_path=rules(tmp_path))
    state = SessionState("recording", [])
    name, said = tracks.label("harmony", state)
    assert name == "Harmony 1" and "renamed" in said and "not mapped yet" in said
    with pytest.raises(gate.Refused):
        tracks.label("kazoo", state)


def test_dry_run_plans_everything_and_touches_nothing():
    tracks = Tracks(run=lambda a: pytest.fail("no osascript in a dry run"), dry_run=True)
    tracks.rename("Lead Vox")
    tracks.color("blue")
    tracks.stack(["Harmony 1", "Harmony 2"])
    assert tracks.planned == ["rename track to Lead Vox", "color track blue", "summing stack: Harmony 1, Harmony 2"]


def test_unmapped_actions_say_so_live(tmp_path):
    tracks = Tracks(run=lambda a: "", conn=gate.connect(":memory:"), rules_path=rules(tmp_path))
    with pytest.raises(NotMapped):
        tracks.stack(["a", "b"])


def test_a_failed_scan_leaves_recording_mode_and_keeps_the_reason():
    def broken(args):
        raise RuntimeError("System Events got an error: whatever")

    state = Tracks(run=broken).scan()
    assert state.mode == "recording" and state.tracks == [] and "System Events" in state.scan_error


def test_a_name_committed_only_to_the_field_is_reported_not_claimed(tmp_path):
    tracks = Tracks(run=lambda a: "renamed\told\tFIELD ONLY: Harmony 1", conn=gate.connect(":memory:"),
                    rules_path=rules(tmp_path))
    with pytest.raises(RuntimeError, match="did not take"):
        tracks.rename("Harmony 1")


def test_the_name_is_read_from_the_quotes_whatever_logic_adds_after_it():
    report = "1\tTrack 1 “Audio 1”, mute\t3\n2\tTrack 2 “Inst 1”\t0\n3\tTrack 3 “Lead, take 2”, solo\t1"
    assert [t.name for t in parse_list(report)] == ["Audio 1", "Inst 1", "Lead, take 2"]
