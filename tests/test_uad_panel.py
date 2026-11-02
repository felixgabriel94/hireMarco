"""The UAD Control Panel read off its window, and the engine's word reconciled with it."""

import datetime as dt
import json

from hiremarco.studio import ledger, uad_panel
from hiremarco.studio.uad_panel import kind_of, match_title, read_panel, reconcile, table_rows


def test_kind_of_reads_the_vendor_vocabulary_and_a_half_recognized_word():
    assert kind_of("Authorized for all devices") == ("owned", None)
    assert kind_of("Autharizad for all davicnd") == ("owned", None)
    assert kind_of("Demo (14 days left)") == ("demo", 14)
    assert kind_of("Demo (1 day left)") == ("demo", 1)
    assert kind_of("START DEMO") == ("not_owned", None)
    assert kind_of("Demo not started") == ("not_owned", None)
    assert kind_of("Demo expired") == ("not_owned", None)
    assert kind_of("UPDATE SOFTWARE") == ("inactive", None)
    assert kind_of("") == ("unknown", None)


def test_table_rows_pairs_each_name_with_the_status_on_its_line():
    texts = [{"y": 128, "x": 80, "text": "Plug-Ins"}, {"y": 298, "x": 34, "text": "PLUG-IN"},
             {"y": 338, "x": 34, "text": "Topline Vocal Tune"}, {"y": 338, "x": 592, "text": "UPDATE SOFTWARE"},
             {"y": 338, "x": 882, "text": "?"}, {"y": 338, "x": 928, "text": "$"},
             {"y": 536, "x": 34, "text": "Shadow Hills Mastering"}, {"y": 540, "x": 300, "text": "Compressor Class A"},
             {"y": 538, "x": 532, "text": "Demo (14 days left)"},
             {"y": 818, "x": 34, "text": "Hitsville Reverb Chambers"}, {"y": 818, "x": 530, "text": "Authorized for all devices"}]
    assert table_rows(texts) == [("Topline Vocal Tune", "UPDATE SOFTWARE"),
                                 ("Shadow Hills Mastering Compressor Class A", "Demo (14 days left)"),
                                 ("Hitsville Reverb Chambers", "Authorized for all devices")]


TITLES = [f"UAD Plug {i:02d}" for i in range(50)]
STATUS = {t: ("Authorized for all devices" if i % 3 else "START DEMO") for i, t in enumerate(TITLES)}
STATUS[TITLES[5]] = "Demo (14 days left)"


class Panel:
    """A fifty-row list, 22 rows in the window, a page of wheel units moving it 15 rows."""

    def __init__(self):
        self.top = 20
        self.captures = 0

    def window(self):
        return 7, 842.0, 113.0, 524.0, 600.0

    def wheel(self, x, y, units):
        assert (x, y) == (842 + 262, 113 + 360)
        self.top = max(0, min(len(TITLES) - 22, self.top - round(units * 15 / 12)))

    def capture(self, wid, path):
        self.captures += 1
        return path

    def recognize(self, path):
        rows = []
        for i, title in enumerate(TITLES[self.top:self.top + 22]):
            name = title.removeprefix("UAD ")
            if i == 3:
                name = name.replace(" ", "")   # a fused read
            rows.append({"y": 338 + 40 * i, "x": 34, "text": name})
            rows.append({"y": 338 + 40 * i, "x": 532, "text": STATUS[title]})
        return rows


def test_read_panel_scrolls_to_the_top_and_pages_to_the_end(tmp_path):
    panel = Panel()
    said = []
    shown = read_panel(scratch=tmp_path, titles=TITLES, settle=0, activate=lambda: None, window=panel.window,
                       capture=panel.capture, recognize=panel.recognize, wheel=panel.wheel, log=said.append)
    assert list(shown) == TITLES and shown == STATUS
    assert panel.top == len(TITLES) - 22 and said[0].endswith("22 rows, 22 new") and said[-1].endswith("0 new")


def test_match_title_takes_the_same_words_in_either_longer_form():
    titles = ["UAD Hitsville EQ Collection", "UAD Shadow Hills Mastering Compressor",
              "UAD Shadow Hills Mastering Compressor Class A", "UAD Manley Reference Microphone Preamplifier",
              "UAD Neve 1084 Preamp and EQ"]
    assert match_title("UAD Hitsville EQ", titles) == "UAD Hitsville EQ Collection"
    assert match_title("UAD Hitsville EQ Mastering", titles) == "UAD Hitsville EQ Collection"
    assert match_title("UAD Shadow Hills Mastering Compressor", titles) == "UAD Shadow Hills Mastering Compressor"
    assert match_title("UAD Shadow Hills Class A Mastering Comp", titles) == "UAD Shadow Hills Mastering Compressor Class A"
    assert match_title("UAD Manley Reference Mic Preamp", titles) == "UAD Manley Reference Microphone Preamplifier"
    assert match_title("UAD Neve 1084", titles) == "UAD Neve 1084 Preamp and EQ"
    assert match_title("UAD Fairchild 670", titles) is None


def test_reconcile_lets_the_engine_decide_and_the_panel_take_out():
    engine = {"UAD Neve 1084": "Authorized for all devices", "UAD Shadow Hills Class A Mastering Comp": "Demo not started",
              "UAD Shadow Hills Mastering Compressor": "Demo not started", "UAD Cambridge EQ": "Authorized for all devices",
              "UAD Topline Vocal Tune": "Update software", "UAD Fairchild 670": "Demo not started"}
    panel = {"UAD Neve 1084 Preamp and EQ": "Authorized for all devices",
             "UAD Shadow Hills Mastering Compressor Class A": "Demo (14 days left)",
             "UAD Shadow Hills Mastering Compressor": "START DEMO", "UAD Cambridge EQ": "START DEMO",
             "UAD Topline Vocal Tune": "UPDATE SOFTWARE"}
    rows = reconcile(engine, panel, today=dt.date(2026, 11, 2))
    assert rows["UAD Neve 1084"] == {"status": "owned", "evidence": ["engine: Authorized for all devices", "panel: Authorized for all devices"]}
    pending = rows["UAD Shadow Hills Class A Mastering Comp"]
    assert pending["status"] == "not_owned" and pending["evidence"][2].startswith("the panel shows a demo the engine has not loaded")
    assert rows["UAD Shadow Hills Mastering Compressor"] == {"status": "not_owned", "evidence": ["engine: Demo not started", "panel: START DEMO"]}
    assert rows["UAD Cambridge EQ"]["status"] == "not_owned" and "disagree" in rows["UAD Cambridge EQ"]["evidence"][2]
    assert rows["UAD Topline Vocal Tune"]["status"] == "inactive"
    assert rows["UAD Fairchild 670"] == {"status": "not_owned", "evidence": ["engine: Demo not started"]}
    live = reconcile({"UAD Shadow Hills Class A Mastering Comp": "Demo (14 days left)"},
                     {"UAD Shadow Hills Mastering Compressor Class A": "Demo (14 days left)"}, today=dt.date(2026, 11, 2))
    assert live["UAD Shadow Hills Class A Mastering Comp"] == {"status": "demo", "evidence": [
        "engine: Demo (14 days left)", "panel: Demo (14 days left)", "demo ends 2026-11-16"]}


def test_the_ledger_takes_the_engine_row_through_logic_s_cut_name():
    uad_rows = {"UAD Shadow Hills Class A Mastering Comp": {"status": "demo", "evidence": ["engine: Demo (14 days left)"]},
                "UAD Shadow Hills Mastering Compressor": {"status": "not_owned", "evidence": ["engine: Demo not started"]},
                "UAD Neve 1084": {"status": "owned", "evidence": ["engine: Authorized for all devices"]},
                "UAD Precision Multiband": {"status": "owned", "evidence": ["engine: Authorized for all devices"]},
                "UAD Precision Multiband Legacy": {"status": "not_owned", "evidence": ["engine: Demo not started"]}}
    names = ["UAD Shadow Hills Class A Master (s/s)", "UAD Shadow Hills Mastering Comp (s/s)", "UAD Neve 1084 (s/s)",
             "UAD Precision Multiband (s/s)", "UAD Nowhere (s/s)", "Pro-Q 3 (s/s)"]
    rows = ledger.build(names, set(), set(), set(), used={"Pro-Q 3"}, presets=set(), registered=set(), present=set(),
                        uad_rows=uad_rows)
    assert rows["UAD Shadow Hills Class A Master (s/s)"] == {"status": "demo", "evidence": [
        "as UAD Shadow Hills Class A Mastering Comp", "engine: Demo (14 days left)"]}
    assert rows["UAD Shadow Hills Mastering Comp (s/s)"]["status"] == "not_owned"
    assert rows["UAD Neve 1084 (s/s)"]["status"] == "owned"
    assert rows["UAD Precision Multiband (s/s)"]["status"] == "owned"   # the exact name wins over the Legacy prefix
    assert rows["UAD Nowhere (s/s)"]["status"] == "unknown"
    assert rows["Pro-Q 3 (s/s)"]["status"] == "owned"
