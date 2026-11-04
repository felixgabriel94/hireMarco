"""His words at the end of a session start the mix check and the master (Owner 2026-11-04)."""

from hiremarco.master.job import STAGES
from hiremarco.studio.commands import asks_to_master, understand


def test_his_closing_sentence_starts_the_master():
    said = "Marco, all right, we're good for today. Could you please mix and master the track?"
    assert understand(said, client=None).action == "export"
    assert understand("Marco, master it.", client=None).action == "export"


def test_a_no_does_not_start_it():
    assert asks_to_master("we're good, mix and master the track")
    assert not asks_to_master("don't master it yet") and not asks_to_master("wait, mix and master later")


def test_the_path_shows_the_mix_checked_before_the_master():
    assert STAGES[0] == "Balance" and STAGES.index("Balance") < STAGES.index("Think")
