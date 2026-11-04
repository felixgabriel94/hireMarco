"""A master to the Owner's phone by link (Owner 2026-11-03).

WhatsApp takes no WAV, so Marco's own server hands the file over the tunnel from a page that is ours: black, the tie
top-left, the wave mark as the cover, the song's name, the real waveform you can drag with a thumb, the time, play
and pause, and the file to download. The link carries an id nobody can guess, good for a day and gone after; nothing
leaves this Mac but the one file the link names. The file goes out in ranges, so the phone plays it in place; the
waveform's peaks are measured once from the file and sent as numbers. The page carries its own cover, which WhatsApp
reads for the card it shows under the link.
"""

from __future__ import annotations

import json
import re
import secrets
import time
from pathlib import Path

from hiremarco import config

TTL_S = 24 * 3600
CHUNK = 1 << 18
PEAKS = 240            # bars across the waveform; enough to find the chorus by eye, light enough for a phone
LOGO = Path(__file__).resolve().parents[1] / "studio" / "assets" / "tie-160.png"


def folder() -> Path:
    return Path(config.STATE_DIR) / "shares"


def slug_for(title: str) -> str:
    """A link's readable name from the song's title: the first letter of each word, lowercase, a version tag such as
    V2 left out ("menos mal se siente bien V2" is mmssb; Owner 2026-11-03: hiremarco.ai/master/mmssb)."""
    words = [w for w in re.findall(r"[A-Za-z0-9]+", title) if not re.fullmatch(r"[vV]\d+", w)]
    return "".join(w[0].lower() for w in words) or secrets.token_urlsafe(6).lower()


def offer(path: Path, *, title: str, note: str, now: float | None = None, slug: str | None = None) -> str:
    """One link's record: the file, its words, its waveform and its cover, and when the link dies. Returns the id:
    the readable slug when one is given (a taken, living slug gets -2, -3), else an unguessable key."""
    folder().mkdir(parents=True, exist_ok=True)
    if slug:
        base = re.sub(r"[^a-z0-9-]", "", slug.lower()) or secrets.token_urlsafe(6).lower()
        share_id, k = base, 2
        while lookup(share_id, now=now) is not None:
            share_id, k = f"{base}-{k}", k + 1
    else:
        share_id = secrets.token_urlsafe(24)
    made = now if now is not None else time.time()
    record = {"id": share_id, "path": str(Path(path).expanduser().resolve()), "name": Path(path).name, "title": title, "note": note,
              "made": made, "expires": made + TTL_S}
    try:
        record["peaks"], record["seconds"] = peaks(Path(path))
    except Exception:   # noqa: BLE001  (an unreadable file still gets its link; the page just has no waveform)
        record["peaks"], record["seconds"] = [], None
    (folder() / f"{share_id}.json").write_text(json.dumps(record))
    try:
        (folder() / f"{share_id}.png").write_bytes(cover(title))
        (folder() / f"{share_id}.card.png").write_bytes(card(title))
    except Exception:   # noqa: BLE001
        pass
    return share_id


def lookup(share_id: str, now: float | None = None) -> dict | None:
    """The record behind an id, or None when there is none, it has expired, or the file is gone."""
    if not share_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in share_id):
        return None
    at = folder() / f"{share_id}.json"
    try:
        record = json.loads(at.read_text())
    except (OSError, ValueError):
        return None
    if (now if now is not None else time.time()) > float(record.get("expires", 0)) or not Path(record["path"]).exists():
        return None
    if record.get("id", share_id) != share_id:   # the Mac's disk ignores case; a link does not
        return None
    return record


def peaks(path: Path, bars: int = PEAKS) -> tuple[list[float], float]:
    """The waveform as ``bars`` levels in 0 to 1, and the length in seconds, read once from the file. Each bar is the
    loudness of its stretch (its RMS), not its tallest sample, scaled so the loud parts sit near the top and the rest
    breathes under them: a master drawn by its peaks reads as a squashed brick (Owner 2026-11-03)."""
    import numpy as np
    import soundfile as sf

    audio, rate = sf.read(str(path), dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    if not mono.size:
        return [], 0.0
    edges = np.linspace(0, mono.size, bars + 1, dtype=int)
    levels = np.array([float(np.sqrt(np.mean(np.square(mono[a:b])))) if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])])
    top = float(np.percentile(levels[levels > 0], 97)) if (levels > 0).any() else 1.0
    scaled = np.clip(levels / (top or 1.0), 0.0, 1.0) * 0.82
    return [round(float(v), 3) for v in scaled], round(mono.size / rate, 2)


WAVE_MARK = [(0.14, 0.5), (0.26, 0.5), (0.31, 0.31), (0.39, 0.73), (0.47, 0.4), (0.54, 0.64), (0.61, 0.46), (0.68, 0.58), (0.75, 0.5), (0.86, 0.5)]


def _mark(d, x: int, y: int, s: int, width: int, color=(255, 255, 255)) -> None:
    d.rounded_rectangle([x, y, x + s, y + s], radius=int(s * 0.19), outline=color, width=width)
    d.line([(x + px * s, y + py * s) for px, py in WAVE_MARK], fill=color, width=width, joint="curve")


def cover(title: str, size: int = 1000) -> bytes:
    """The player's art: black, the wave mark alone (Owner 2026-11-03: the page names the song once, under the mark)."""
    import io

    from PIL import Image, ImageDraw

    im = Image.new("RGB", (size, size), (0, 0, 0))
    d = ImageDraw.Draw(im)
    s = int(size * 0.5)
    _mark(d, (size - s) // 2, (size - s) // 2, s, max(4, int(size * 0.02)))
    out = io.BytesIO()
    im.save(out, format="PNG", optimize=True)
    return out.getvalue()


def card(title: str, size: int = 1000) -> bytes:
    """The card WhatsApp shows under the link, square so its small thumbnail is the whole picture and not a slice of it
    (Owner 2026-11-03, option A): black, the tie and the name top-left, the wave mark, the song's name, MASTER, a quiet
    line and Mastered by Marco."""
    import io

    from PIL import Image, ImageDraw

    im = Image.new("RGBA", (size, size), (0, 0, 0, 255))
    d = ImageDraw.Draw(im)
    try:
        tie = Image.open(LOGO).convert("RGBA").resize((52, 52))
        im.alpha_composite(tie, (48, 44))
    except OSError:
        pass
    d.text((112, 70), "hireMarco", font=_font(30), fill=(255, 255, 255), anchor="lm")
    _mark(d, size // 2 - 130, 250, 260, 12)
    d.text((size / 2, 620), title, font=_font(50), fill=(255, 255, 255), anchor="mm")
    d.text((size / 2, 690), "MASTER", font=_font(24, mono=True), fill=(138, 138, 138), anchor="mm")
    d.line([(80, 820), (size - 80, 820)], fill=(40, 40, 40), width=2)
    d.text((size / 2, 880), "Mastered by Marco", font=_font(26), fill=(138, 138, 138), anchor="mm")
    out = io.BytesIO()
    im.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


def _font(size: int, mono: bool = False):
    from PIL import ImageFont

    names = ["/System/Library/Fonts/Supplemental/Menlo.ttc"] if mono else ["/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def base_url() -> str | None:
    """Where the phone reaches this Mac's /share: the call relay's tunnel, else the home network. SHARE_URL, when set,
    is the public address that stands for /share (hiremarco.ai/m, or a tunnel's host plus /share) and link() uses it."""
    relay = config.get("CALL_RELAY_URL")
    if relay:
        return relay.split("/llm/")[0].rstrip("/")
    from hiremarco.studio.live import lan_address

    lan = lan_address()
    return f"http://{lan}:8787" if lan else None


def link(share_id: str) -> str:
    """The address the Owner gets: under SHARE_URL when one is set (hiremarco.ai/m, which the website passes through
    to this server's /share), else this server's own /share on the tunnel."""
    own = config.get("SHARE_URL")
    if own:
        return f"{own.rstrip('/')}/{share_id}"
    base = base_url()
    if not base:
        raise RuntimeError("no address the phone can reach: no tunnel and no home network")
    return f"{base}/share/{share_id}"


def page_html(record: dict, share_id: str, base: str) -> str:
    """The player, minimal and centred (Owner 2026-11-03): the brand once, the mark, the song's name once, MASTER, the
    waveform to drag, the time, back, one play-and-pause button, forward, and Download the WAV. Nothing else."""
    title, name = _esc(record["title"]), _esc(record["name"])
    # the page's own pieces are reached by paths beside the page, so they go wherever the page came through (the
    # website's /m passthrough or this server's /share); the card's picture must be a whole address, under SHARE_URL
    # when one is set, else this server's
    here = share_id
    public = (config.get("SHARE_URL") or "").rstrip("/")
    card_url = f"{public}/{share_id}/card.png" if public else f"{base}/share/{share_id}/card.png"
    peaks_json = json.dumps(record.get("peaks") or [])
    seconds = json.dumps(record.get("seconds") or 0)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#000000">
<meta property="og:title" content="{title}">
<meta property="og:description" content="Master, by Marco at hireMarco.">
<meta property="og:image" content="{card_url}">
<meta property="og:type" content="music.song">
<title>{title}</title>
<style>
html, body {{ margin: 0; height: 100%; background: #000; color: #fff; font: 16px/1.5 -apple-system, "Inter", sans-serif; -webkit-tap-highlight-color: transparent; }}
body {{ display: flex; flex-direction: column; align-items: center; box-sizing: border-box; min-height: 100%; padding: calc(env(safe-area-inset-top) + 14px) 20px calc(env(safe-area-inset-bottom) + 24px); }}
#brand {{ align-self: flex-start; display: flex; align-items: center; gap: 10px; }}
#brand img {{ width: 32px; height: 32px; }} #brand span {{ font-weight: 600; letter-spacing: .02em; font-size: 15px; }}
#stage {{ flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; width: 100%; max-width: 420px; gap: 0; }}
#art {{ width: 112px; height: 112px; display: block; }}
h1 {{ font-size: 20px; line-height: 1.25; margin: 26px 0 2px; font-weight: 600; text-align: center; }}
.by {{ color: #8a8a8a; margin: 0 0 26px; font: 12px "JetBrains Mono", Menlo, monospace; letter-spacing: .14em; }}
#wave {{ display: block; width: 100%; height: 56px; touch-action: none; }}
#time {{ color: #8a8a8a; font: 13px "JetBrains Mono", Menlo, monospace; margin: 10px 0 14px; }}
#ctl {{ display: flex; justify-content: center; align-items: center; gap: 38px; }}
#ctl button {{ background: none; border: 0; color: #fff; padding: 6px; }}
#ctl svg {{ width: 26px; height: 26px; fill: #fff; display: block; }} #play svg {{ width: 40px; height: 40px; }}
[hidden] {{ display: none !important; }}
a.get {{ display: inline-block; margin-top: 34px; color: #fff; text-decoration: none; border: 1px solid #333; padding: 10px 20px; border-radius: 999px; font-size: 14px; }}
@media (orientation: landscape) {{ #art {{ width: 72px; height: 72px; }} h1 {{ margin-top: 12px; }} .by {{ margin-bottom: 12px; }} a.get {{ margin-top: 16px; }} }}
</style></head>
<body>
<div id="brand"><img src="{here}/tie.png" alt=""><span>hireMarco</span></div>
<div id="stage">
<img id="art" src="{here}/cover.png" alt="">
<h1>{title}</h1>
<p class="by">MASTER</p>
<canvas id="wave" width="1000" height="112"></canvas>
<div id="time">0:00 / 0:00</div>
<div id="ctl">
<button id="back" aria-label="Back ten seconds"><svg viewBox="0 0 24 24"><path d="M11 18V6l-8.5 6 8.5 6zm.5-6l8.5 6V6l-8.5 6z"/></svg></button>
<button id="play" aria-label="Play"><svg id="ic-play" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg><svg id="ic-pause" viewBox="0 0 24 24" hidden><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg></button>
<button id="fwd" aria-label="Forward ten seconds"><svg viewBox="0 0 24 24"><path d="M4 18l8.5-6L4 6v12zm9-12v12l8.5-6L13 6z"/></svg></button>
</div>
<audio id="audio" preload="metadata" src="{here}/file"></audio>
<a class="get" href="{here}/file" download="{name}">Download the WAV</a>
</div>
<script>
const peaks = {peaks_json}, length = {seconds};
const audio = document.getElementById("audio"), wave = document.getElementById("wave"), ctx = wave.getContext("2d");
const timeEl = document.getElementById("time"), playBtn = document.getElementById("play");
let dragging = false, dragAt = 0;
function fmt(s) {{ s = Math.max(0, Math.floor(s || 0)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); }}
function total() {{ return (isFinite(audio.duration) && audio.duration) || length || 0; }}
function draw() {{
  const w = wave.width, h = wave.height, n = peaks.length || 1, gap = w / n, bw = Math.max(1.5, gap * 0.4);
  const at = dragging ? dragAt : (total() ? audio.currentTime / total() : 0);
  ctx.clearRect(0, 0, w, h);
  for (let i = 0; i < n; i++) {{
    const p = Math.max(peaks[i] || 0, 0.03), bh = Math.max(3, p * (h - 6));
    ctx.fillStyle = (i / n) <= at ? "#5c9bff" : "#ffffff";
    ctx.globalAlpha = (i / n) <= at ? 1 : 0.5;
    ctx.beginPath(); ctx.roundRect(i * gap + (gap - bw) / 2, (h - bh) / 2, bw, bh, 1); ctx.fill();
  }}
  ctx.globalAlpha = 1; ctx.fillStyle = "#5c9bff"; ctx.fillRect(at * w - 1, 0, 2, h);
  timeEl.textContent = fmt((dragging ? dragAt * total() : audio.currentTime)) + " / " + fmt(total());
}}
function seekTo(clientX) {{ const r = wave.getBoundingClientRect(); dragAt = Math.min(1, Math.max(0, (clientX - r.left) / r.width)); draw(); }}
wave.addEventListener("pointerdown", (e) => {{ dragging = true; wave.setPointerCapture(e.pointerId); seekTo(e.clientX); }});
wave.addEventListener("pointermove", (e) => {{ if (dragging) seekTo(e.clientX); }});
wave.addEventListener("pointerup", (e) => {{ if (!dragging) return; seekTo(e.clientX); dragging = false; if (total()) audio.currentTime = dragAt * total(); draw(); }});
wave.addEventListener("pointercancel", () => {{ dragging = false; draw(); }});
playBtn.onclick = () => {{ if (audio.paused) audio.play(); else audio.pause(); }};
document.getElementById("back").onclick = () => {{ audio.currentTime = Math.max(0, audio.currentTime - 10); }};
document.getElementById("fwd").onclick = () => {{ audio.currentTime = Math.min(total(), audio.currentTime + 10); }};
audio.addEventListener("play", () => {{ document.getElementById("ic-play").hidden = true; document.getElementById("ic-pause").hidden = false; }});
audio.addEventListener("pause", () => {{ document.getElementById("ic-play").hidden = false; document.getElementById("ic-pause").hidden = true; }});
audio.addEventListener("timeupdate", draw); audio.addEventListener("loadedmetadata", draw);
function tick() {{ if (!audio.paused) draw(); requestAnimationFrame(tick); }}
draw(); requestAnimationFrame(tick);
</script>
</body></html>
"""


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def routes() -> list:
    """GET /share/{id}: the page. /file: the WAV, whole or by range. /cover.png: the cover. /tie.png: the tie."""
    from starlette.responses import HTMLResponse, Response, StreamingResponse
    from starlette.routing import Route

    async def page(request):
        record = lookup(request.path_params["share_id"])
        if record is None:
            return Response(status_code=404)
        base = str(request.base_url).rstrip("/")
        return HTMLResponse(page_html(record, request.path_params["share_id"], base), headers={"Cache-Control": "no-store"})

    async def file(request):
        record = lookup(request.path_params["share_id"])
        if record is None:
            return Response(status_code=404)
        path = Path(record["path"])
        size = path.stat().st_size
        start, end = 0, size - 1
        wanted = request.headers.get("range", "")
        partial = wanted.startswith("bytes=")
        if partial:
            first, _, last = wanted[6:].partition("-")
            try:
                start = int(first) if first else max(size - int(last), 0)
                end = min(int(last), size - 1) if last and first else end
            except ValueError:
                return Response(status_code=416)
            if start > end or start >= size:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})

        def body():
            with path.open("rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    piece = f.read(min(CHUNK, left))
                    if not piece:
                        break
                    left -= len(piece)
                    yield piece

        headers = {"Accept-Ranges": "bytes", "Content-Length": str(end - start + 1), "Cache-Control": "no-store",
                   "Content-Disposition": f'inline; filename="{record["name"]}"'}
        if partial:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return StreamingResponse(body(), status_code=206 if partial else 200, media_type="audio/wav", headers=headers)

    async def art(request):
        share_id = request.path_params["share_id"]
        record = lookup(share_id)
        if record is None:
            return Response(status_code=404)
        at = folder() / f"{share_id}.png"
        data = at.read_bytes() if at.exists() else cover(record["title"])
        return Response(data, media_type="image/png", headers={"Cache-Control": "max-age=86400"})

    async def card_png(request):
        share_id = request.path_params["share_id"]
        record = lookup(share_id)
        if record is None:
            return Response(status_code=404)
        at = folder() / f"{share_id}.card.png"
        data = at.read_bytes() if at.exists() else card(record["title"])
        return Response(data, media_type="image/png", headers={"Cache-Control": "max-age=86400"})

    async def tie(request):
        if lookup(request.path_params["share_id"]) is None:
            return Response(status_code=404)
        return Response(LOGO.read_bytes(), media_type="image/png", headers={"Cache-Control": "max-age=86400"})

    return [Route("/share/{share_id}", page), Route("/share/{share_id}/file", file), Route("/share/{share_id}/cover.png", art),
            Route("/share/{share_id}/card.png", card_png), Route("/share/{share_id}/tie.png", tie)]
