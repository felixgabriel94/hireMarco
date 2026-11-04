"""A master by link: a page of ours, the file whole or by range, an id that dies after a day, and nothing else served."""

import numpy as np
import soundfile as sf
from starlette.applications import Starlette
from starlette.testclient import TestClient

from hiremarco import config
from hiremarco.master import share


def wav(tmp_path):
    path = tmp_path / "song - master 2026-11-03.wav"
    tone = 0.5 * np.sin(np.linspace(0, 2 * np.pi * 440 * 0.1, 4800, dtype="float32"))
    sf.write(str(path), np.column_stack([tone, tone]), 48000, subtype="PCM_24")
    return path


def test_the_link_serves_a_branded_page_the_file_and_the_tie_until_it_dies(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    path = wav(tmp_path)
    share_id = share.offer(path, title="menos mal se siente bien V2", note="Master, demo: -11.0 LUFS integrated, true peak -1.0 dBTP.")
    client = TestClient(Starlette(routes=share.routes()))
    page = client.get(f"/share/{share_id}")
    assert page.status_code == 200 and "background: #000" in page.text and "hireMarco" in page.text
    assert "menos mal se siente bien V2" in page.text and "-11.0 LUFS" in page.text and ">MASTER<" in page.text
    assert f'src="http://testserver/share/{share_id}/file"' in page.text and 'download="song - master 2026-11-03.wav"' in page.text
    assert client.get(f"/share/{share_id}/tie.png").headers["content-type"] == "image/png"
    art = client.get(f"/share/{share_id}/cover.png")
    assert art.headers["content-type"] == "image/png" and art.content[:8] == b"\x89PNG\r\n\x1a\n" and len(art.content) > 2000
    assert f'property="og:image" content="http://testserver/share/{share_id}/cover.png"' in page.text
    assert 'id="wave"' in page.text and "pointerdown" in page.text and "const peaks = [" in page.text and '"MASTER"' not in page.text
    record = share.lookup(share_id)
    assert len(record["peaks"]) == share.PEAKS and max(record["peaks"]) == 1.0 and abs(record["seconds"] - 0.1) < 0.01
    whole = client.get(f"/share/{share_id}/file")
    assert whole.status_code == 200 and whole.headers["accept-ranges"] == "bytes" and len(whole.content) == path.stat().st_size
    part = client.get(f"/share/{share_id}/file", headers={"Range": "bytes=10-19"})
    assert part.status_code == 206 and part.headers["content-range"] == f"bytes 10-19/{path.stat().st_size}" and len(part.content) == 10
    tail = client.get(f"/share/{share_id}/file", headers={"Range": "bytes=-5"})
    assert tail.status_code == 206 and len(tail.content) == 5
    assert client.get(f"/share/{share_id}/file", headers={"Range": "bytes=99999999-"}).status_code == 416
    assert client.get("/share/nope").status_code == 404 and client.get("/share/../etc").status_code in (404, 400)
    made = share.lookup(share_id)["made"]
    assert share.lookup(share_id, now=made + share.TTL_S - 1) is not None and share.lookup(share_id, now=made + share.TTL_S + 1) is None
    path.unlink()
    assert share.lookup(share_id) is None


def test_the_link_goes_through_the_tunnel_when_there_is_one(monkeypatch):
    monkeypatch.setattr(config, "get", lambda key, default=None: "https://marco.example.ngrok-free.dev/llm/v1" if key == "CALL_RELAY_URL" else default)
    assert share.base_url() == "https://marco.example.ngrok-free.dev"
    assert share.link("abc").endswith("/share/abc")
