"""The song's own cover on its player page; the WhatsApp card stays the wave mark (Owner 2026-11-04)."""

import io

from PIL import Image

from hiremarco.master import share


def test_menos_mal_gets_its_cover_and_another_song_the_wave_mark():
    for title in ("menos mal se siente bien V2", '"menos mal se siente bien" (demo)', "Menos Mal Se Siente Bien"):
        assert share.cover_art(title) == share.COVERS["menos mal se siente bien"]
    art = Image.open(io.BytesIO(share.cover("menos mal se siente bien V2")))
    painted = Image.open(share.COVERS["menos mal se siente bien"]).convert("RGB").resize((1000, 1000), Image.LANCZOS)
    assert art.size == (1000, 1000) and art.convert("RGB").getpixel((600, 545)) == painted.getpixel((600, 545))
    assert share.cover_art("another song") is None
    assert share.cover("another song") != share.cover("menos mal se siente bien V2")


def test_the_whatsapp_card_stays_the_wave_mark():
    assert share.card("menos mal se siente bien V2") == share.card("another song")
