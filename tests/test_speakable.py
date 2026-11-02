"""Music the way it is said (live 2026-10-31: 'A major' came out 'uh major')."""

from hiremarco.voice.tts import speakable


def test_keys_and_notes_are_said_like_a_musician_says_them():
    assert speakable("Session's ready: A major, 99 BPM.") == "Session's ready: Eigh major, 99 BPM."
    assert speakable("We're in F# minor.") == "We're in F sharp minor."
    assert speakable("Bb major, then Am.") == "B flat major, then Eigh minor."
    assert speakable("The third above is G A B.") == "The third above is G Eigh B."
    assert speakable("the key of A") == "the key of Eigh"


def test_a_capital_a_that_is_a_word_stays():
    assert speakable("A beat arrived. A lot of reverb.") == "A beat arrived. A lot of reverb."


def test_a_line_never_opens_with_hmm():
    assert speakable("Hmm. Let me check the take.") == "Let me check the take."
    assert speakable("Mm, okay, rolling.") == "okay, rolling."
    assert speakable("Hmm") == ""                                        # nothing else in it, so nothing to say


def test_thinking_sounds_go_anywhere_in_a_line():
    assert speakable("Okay, uh, rolling.") == "Okay, rolling."
    assert speakable("Let me uh check the take.") == "Let me check the take."
    assert speakable("That one was crazy, hmm.") == "That one was crazy."
    assert speakable("Nice take. Mm. Want another?") == "Nice take. Want another?"
    assert speakable("So um, lead or double?") == "So, lead or double?"
    assert speakable("Mm-hm, got it.") == "got it."
    assert speakable("Mhm. Uhh, umm, we're good.") == "we're good."
    assert speakable("hmm mm uh um") == ""


def test_real_words_are_not_mangled():
    for line in ("The umbrella's here, mum.", "Uh-oh, that clipped.", "A 35 mm lens, shot at the UM campus.",
                 "Hummingbird on the hum of the amp.", "Summer's mmm-good.", "Your mic is an MM1."):
        assert speakable(line) == line
