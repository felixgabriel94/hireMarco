"""The hearing stack: called when installed, glossed for the brain, absent without a fuss."""

import json
import subprocess
from types import SimpleNamespace

from hiremarco.mix import listen as listening

HEARD = {"psychoacoustics": {"loudness_sone_mean": 31.2, "loudness_sone_max": 48.0, "sharpness_acum_mean": 1.42,
                             "roughness_asper_mean": 0.21, "took_s": 9.1},
         "audiobox_aesthetics": {"mix": {"CE": 6.1, "CU": 7.0, "PC": 5.2, "PQ": 6.8}, "took_s": 20.0},
         "clap": {"words": {"a loud, bright, modern master": 0.31, "a dark, muddy mix": 0.12}, "took_s": 8.0},
         "zimtohrli": {"sample_rate": 48000, "mix_vs_itself": 0.0, "mos_mix_vs_reference": 3.4, "took_s": 1.0},
         "stems": {"lufs": {"vocals": -21.0, "drums": -19.5, "bass": -24.0, "other": -26.0}, "vocal_over_rest_db": -0.4, "took_s": 90.0}}


def stack(tmp_path):
    (tmp_path / "env" / "bin").mkdir(parents=True)
    (tmp_path / "env" / "bin" / "python").write_text("")
    (tmp_path / "listen.py").write_text("")
    return tmp_path


def test_absent_stack_means_no_hearing(tmp_path):
    assert listening.listen(tmp_path / "mix.wav", home=tmp_path / "nowhere") is None


def test_the_stack_is_run_in_its_own_interpreter_and_its_json_read(tmp_path):
    seen = []

    def run(args, **kw):
        seen.append(args)
        return SimpleNamespace(returncode=0, stdout=json.dumps(HEARD), stderr="")

    home = stack(tmp_path)
    heard = listening.listen(tmp_path / "mix.wav", tmp_path / "ref.wav", home=home, run=run)
    assert heard == HEARD
    assert seen[0][:3] == [str(home / "env" / "bin" / "python"), "-I", str(home / "listen.py")]
    assert seen[0][3:] == [str(tmp_path / "mix.wav"), str(tmp_path / "ref.wav")]


def test_a_failing_stack_answers_with_an_error_not_a_stop(tmp_path):
    home = stack(tmp_path)
    boom = listening.listen(tmp_path / "mix.wav", home=home,
                            run=lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="ImportError: torch"))
    assert boom == {"error": "ImportError: torch"}

    def slow(args, **kw):
        raise subprocess.TimeoutExpired(args, kw.get("timeout", 0))

    assert "took over" in listening.listen(tmp_path / "mix.wav", home=home, run=slow, timeout=5)["error"]


def test_the_gloss_and_the_highlights_read_as_an_engineer_would():
    glossed = listening.for_model(HEARD)
    assert "sone" in glossed["psychoacoustics"]["what"] and "took_s" not in glossed["psychoacoustics"]["heard"]
    assert glossed["audiobox_aesthetics"]["heard"]["mix"]["PQ"] == 6.8
    lines = listening.highlights(HEARD)
    assert lines[0].startswith("heard: 31.2 sone") and "Audiobox: CE 6.1, CU 7.0, PC 5.2, PQ 6.8" in lines
    assert any("modern master" in l for l in lines) and "against the reference: 3.40 of 5 alike" in lines
    assert lines[-1] == "stems (LUFS): vocals -21.0, drums -19.5, bass -24.0, other -26.0; the vocal sits -0.4 dB against the rest"
    assert "Demucs" in glossed["stems"]["what"]
    assert listening.for_model(None) is None and listening.highlights({"error": "x"}) == ["the hearing stack failed: x"]
