"""A master to the Owner's phone by link (Owner 2026-11-03).

WhatsApp takes no WAV, so Marco's own server hands the file over the tunnel from a page that is ours: black, the tie
top-left, the song's name, the master's numbers, play and download. The link carries an id nobody can guess, good
for a day and gone after; nothing leaves this Mac but the one file the link names. The file goes out in ranges, so
the phone can play it in place before it downloads it.
"""

from __future__ import annotations

import json
import secrets
import time
from pathlib import Path

from hiremarco import config

TTL_S = 24 * 3600
CHUNK = 1 << 18
LOGO = Path(__file__).resolve().parents[1] / "studio" / "assets" / "tie-160.png"


def folder() -> Path:
    return Path(config.STATE_DIR) / "shares"


def offer(path: Path, *, title: str, note: str, now: float | None = None) -> str:
    """One link's record: the file, its words and when the link dies. Returns the id."""
    share_id = secrets.token_urlsafe(24)
    folder().mkdir(parents=True, exist_ok=True)
    record = {"path": str(Path(path).expanduser().resolve()), "name": Path(path).name, "title": title, "note": note,
              "made": now if now is not None else time.time(), "expires": (now if now is not None else time.time()) + TTL_S}
    (folder() / f"{share_id}.json").write_text(json.dumps(record))
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
    return record


def base_url() -> str | None:
    """Where the phone reaches this Mac: the tunnel's address when the call relay has one, else the home network."""
    relay = config.get("CALL_RELAY_URL")
    if relay:
        return relay.split("/llm/")[0].rstrip("/")
    from hiremarco.studio.live import lan_address

    lan = lan_address()
    return f"http://{lan}:8787" if lan else None


def link(share_id: str) -> str:
    base = base_url()
    if not base:
        raise RuntimeError("no address the phone can reach: no tunnel and no home network")
    return f"{base}/share/{share_id}"


def page_html(record: dict, share_id: str, base: str) -> str:
    title, note, name = _esc(record["title"]), _esc(record["note"]), _esc(record["name"])
    here = f"{base}/share/{share_id}"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#000000">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{note}">
<meta property="og:image" content="{here}/tie.png">
<title>{title}</title>
<style>
html, body {{ margin: 0; min-height: 100%; background: #000; color: #fff; font: 16px/1.5 -apple-system, "Inter", sans-serif; }}
body {{ padding: calc(env(safe-area-inset-top) + 18px) 20px calc(env(safe-area-inset-bottom) + 24px); box-sizing: border-box; }}
#brand {{ display: flex; align-items: center; gap: 10px; }}
#brand img {{ width: 40px; height: 40px; }} #brand span {{ font-weight: 600; letter-spacing: .02em; }}
h1 {{ font-size: 26px; line-height: 1.2; margin: 40px 0 6px; font-weight: 600; }}
.by {{ color: #8a8a8a; margin: 0 0 28px; }}
audio {{ width: 100%; margin: 0 0 24px; }}
.note {{ color: #bdbdbd; font-size: 14px; margin: 0 0 28px; }}
a.get {{ display: inline-block; background: #fff; color: #000; text-decoration: none; padding: 12px 20px; border-radius: 999px; font-weight: 600; }}
.file {{ color: #666; font-size: 13px; margin-top: 18px; word-break: break-all; }}
@media (orientation: landscape) {{ body {{ max-width: 720px; margin: 0 auto; }} }}
</style></head>
<body>
<div id="brand"><img src="{here}/tie.png" alt=""><span>hireMarco</span></div>
<h1>{title}</h1>
<p class="by">Mastered by Marco</p>
<audio controls preload="metadata" src="{here}/file"></audio>
<p class="note">{note}</p>
<a class="get" href="{here}/file" download="{name}">Download the WAV</a>
<p class="file">{name}</p>
</body></html>
"""


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def routes() -> list:
    """GET /share/{id}: the page. GET /share/{id}/file: the WAV, whole or by range. GET /share/{id}/tie.png: the tie."""
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

    async def tie(request):
        if lookup(request.path_params["share_id"]) is None:
            return Response(status_code=404)
        return Response(LOGO.read_bytes(), media_type="image/png", headers={"Cache-Control": "max-age=86400"})

    return [Route("/share/{share_id}", page), Route("/share/{share_id}/file", file), Route("/share/{share_id}/tie.png", tie)]
