"""Build Marco Live's page from the Owner's design: the design stays as he sent it (trace/design.html); this makes
trace/index.html, with no network: the sample out, the fonts and the Gmail icon from trace/assets beside it, and the header's
count of calls counting Meta model calls only, since Marco's own long steps also run with a clock. A finished line says
what happened: a step is done, SAM found, Muse Image painted, Voice Transcribe heard, a judging model decided. Run it
again when the design changes.

    uv run python scripts/build_live_page.py
"""

from __future__ import annotations

import re
from pathlib import Path

TRACE = Path(__file__).resolve().parent.parent / "src" / "hiremarco" / "trace"


def build(design: str) -> str:
    page, sample = re.subn(r'<!-- SAMPLE DATA.*?</script>\s*', "", design, count=1, flags=re.S)
    page, links = re.subn(r'<!-- Design-time fonts.*?-->\s*<link[^>]*>\s*<link[^>]*>\s*', "", page, count=1, flags=re.S)
    faces = ('@font-face{font-family:"Inter Tight";font-weight:400 600;src:url("assets/InterTight-latin.woff2") format("woff2")}\n'
             '@font-face{font-family:"JetBrains Mono";font-weight:400 700;src:url("assets/JetBrainsMono-latin.woff2") format("woff2")}\n')
    page, styled = re.subn(r"<style>\n", "<style>\n" + faces, page, count=1)
    page, icon = re.subn(r'src="gmail\.webp"', 'src="assets/gmail.webp"', page, count=1)
    tally = "const n=S.calls.size;const t=$('tally')"
    counted = "const n=[...S.calls.values()].filter(c=>MODELS.some(m=>m.key===c.key)).length;const t=$('tally')"
    decided = "const lab=st==='error'?'failed':st==='held'?'held':'decided';"
    worded = "const lab=st==='error'?'failed':st==='held'?'held':({sam31:'found',museimage10:'painted',musevoicetranscribe10:'heard'}[l.key]||(MODELS.some(m=>m.key===l.key)?'decided':'done'));"
    if not (sample and links and styled and icon and tally in page and decided in page):
        raise SystemExit(f"the design changed shape: sample {sample}, fonts {links}, style {styled}, icon {icon}, tally {tally in page}, decided {decided in page}")
    # the mode's word on screen (the design carries it hidden): a replay must not pass as live; and the path keeps Deliver in
    # frame when a step back marks several stages
    extra = ".mode .mlabel{display:inline}.mode.replay .mlabel{color:var(--catch)}.mode.live .mlabel{color:var(--accent)}\n.banner #path{gap:0 14px}\n"
    return page.replace(tally, counted).replace(decided, worded).replace("</style>", extra + "</style>", 1)


if __name__ == "__main__":
    out = build((TRACE / "design.html").read_text())
    (TRACE / "index.html").write_text(out)
    print(f"{TRACE / 'index.html'}: {len(out)} characters, network references: {len(re.findall(r'https?://(?!www.w3.org)', out))}")
