import unicodedata
from pathlib import Path

import numpy as np
import soundfile as sf

from hiremarco.studio import samples


def test_a_sound_is_named_by_its_file_first_then_its_folders_and_the_pack_name_last():
    root = Path("/packs")
    kind = lambda rel: samples.kind_of(root / rel, root)  # noqa: E731
    assert kind("Loopgoonz - Oh GAWD Drumkit/Snarez (LG)/Snare (TrapOnBoi).wav") == "snare"   # "Oh" is the pack's
    assert kind("Sizzles 808 Mafia Kit/Percs/15 Tubular-Bell.wav") == "instrument"            # "808" is the pack's
    assert kind("Tainy/Afro/One_Shots/Drums/Perc/SS_SD_shaker_trash.wav") == "hat"           # "SD" is no snare
    assert kind("Kit/Hats/Open/8 ( OpenHat).wav") == "open hat"
    assert kind("JR Kit/OH/JR - Wave.wav") == "open hat"
    assert kind("Kit/808s/Zay 808.wav") == "808"
    assert kind("Vocals/Laurie Webb Shake.wav") == "vocal"                                    # the pack says it
    assert kind("Kit/MIDI/Bounce.mid") == "midi"
    assert kind("Kit/Misc/thing 7.wav") == ""


def test_loop_names_give_their_tempo_and_key():
    assert samples.tempo_of("Brentwood - Gm - 106 BPM.mp3") == 106
    assert samples.tempo_of("Cuba 140bpm.mp3") == 140
    assert samples.tempo_of("Kick 9.wav") == 0
    assert samples.key_of("Brentwood - Gm - 106 BPM") == "G minor"
    assert samples.key_of("AlterEgo Sample 5 (Fmin 110BPM)") == "F minor"
    assert samples.key_of("Pad C major") == "C major"
    assert samples.key_of("Kick 9") == ""


def test_a_folder_line_outranks_its_packs_line_and_accents_match_however_spelled():
    packs = {"Tainy": "reggaeton", "Tainy/Afro Dancehall": "afrobeats",
             unicodedata.normalize("NFC", "Loops - By Julián"): "reggaeton"}
    assert samples.genre_of(("Tainy", "Afro Dancehall", "Kicks", "k.wav"), packs) == "afrobeats"
    assert samples.genre_of(("Tainy", "Dembow", "k.wav"), packs) == "reggaeton"
    decomposed = unicodedata.normalize("NFD", "Loops - By Julián")
    assert samples.genre_of((decomposed, "a.wav"), packs) == "reggaeton"


def _wav(path: Path, seconds: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.zeros(int(48000 * seconds), dtype="float32"), 48000)


def test_the_catalog_holds_every_sound_where_it_is_with_its_genre_and_kind(tmp_path):
    root = tmp_path / "My Packs"
    _wav(root / "Afro Kit" / "Kick" / "Kick 01.wav", 0.4)
    _wav(root / "Afro Kit" / "Percussion" / "Perc 05.wav", 0.3)
    _wav(root / "Trap Kit" / "Kicks" / "Big Kick.wav", 0.4)
    _wav(root / "Trap Kit" / "Misc" / "Ride Out 140 BPM.wav", 6.0)
    _wav(root / "Trap Kit" / "Misc" / "thing.wav", 0.2)
    conn = samples.connect(tmp_path / "catalog.sqlite")
    counts = samples.scan(root, {"Afro Kit": "afrobeats", "Trap Kit": "trap"}, conn, ear=lambda p: "snare")
    assert counts == {"kick": 2, "perc": 1, "loop": 1, "snare": 1}
    kicks = samples.find("kick", "afrobeats", conn)
    assert [k.pack for k in kicks] == ["Afro Kit", "Trap Kit"]                               # its genre first
    assert [k.pack for k in samples.find("kick", "afrobeats", conn, only=True)] == ["Afro Kit"]
    loop = samples.find("loop", "", conn)[0]
    assert (loop.bpm, loop.path.exists()) == (140, True)                                     # nothing moved


def test_the_closest_sound_on_the_shelf_comes_first(tmp_path):
    shelf = [samples.Sound(tmp_path / n, "p", "afrobeats", "kick", 0.3, 0, "") for n in ("a", "b", "c")]
    shapes = {"a": np.array([1.0, 0.0]), "b": np.array([0.6, 0.8]), "c": np.array([0.0, 1.0])}
    best = samples.closest(shelf, np.array([0.0, 1.0]), load=lambda p: shapes[p.name], top=2)
    assert [s.path.name for _, s in best] == ["c", "b"]


def test_a_song_carries_the_genre_he_gave_it(tmp_path):
    songs = tmp_path / "songs.tsv"
    songs.write_text("# notes\naguacero\tafrobeats\n")
    assert samples.song_genre("Aguacero", songs) == "afrobeats"
    assert samples.song_genre("other", songs) == ""
