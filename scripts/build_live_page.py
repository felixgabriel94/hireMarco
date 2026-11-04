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
    # a step that is a test or a check ends with its own word (tested, checked); done is kept for a finished result, and
    # a running test says testing (Owner 2026-11-03)
    worded = worded.replace("'decided':'done'))", "'decided':(l.word||'done')))")   # one more paren: the group it opens
    # the mind's own copy of that line reads the focused call, not a slot line (live 2026-11-03: the page built since
    # noon had a paren short and a stray `l` here, and the TV kept showing yesterday's page because it never reloaded)
    decided_focus = decided + "const sum=focus.summary"
    worded_focus = worded.replace("l.key", "focus.key").replace("l.word", "focus.word") + "const sum=focus.summary"
    using = "wd('using','use')"
    testing = "wd(l.word?l.word.replace(/ed$/,'ing'):'using','use')"
    # a model's light is on for as long as a call of its runs, whether or not its line is in a slot on screen; a finished
    # run leaves its count behind so the header counts this job's calls, not the day's (Owner 2026-11-03)
    shown = "const shown=(S.slots||[]).filter(l=>l&&l.kind==='call');"
    lit = "const shown=[...S.calls.values()].filter(l=>l.status==='running').concat((S.slots||[]).filter(l=>l&&l.kind==='call'));"
    run_start = "S.runs++;}"
    run_reset = "S.runs++;S.calls=new Map();S.catches=0;}"
    # the wave file mark (Owner 2026-11-03, option B): a square tile with a waveform for anything that is a song file, the
    # final version saved, the file sent, the file measured; the meter mark stays for loudness work. Joins the studio
    # family so the no-repeat rule rotates it like the others
    eq_mark = "if(mo==='eq')return"
    wavefile_mark = ("if(mo==='wavefile')return '<span class=\"mk sv wavefile\"><svg viewBox=\"0 0 30 38\"><rect x=\"2\" y=\"2\" width=\"26\" height=\"26\" rx=\"5\"/>"
                     "<path d=\"M6 15 L9 15 L10.5 10 L12.5 20 L14.5 11.5 L16.5 18 L18.5 13 L20.5 16 L22.5 14.5 L24 15\"/>"
                     "<text x=\"15\" y=\"36.5\" text-anchor=\"middle\" font-size=\"7.5\" font-family=\"JetBrains Mono, Menlo, monospace\" letter-spacing=\"1\" fill=\"currentColor\" stroke=\"none\">WAV</text>"
                     "</svg></span>';\n " + eq_mark)   # with the label (Owner 2026-11-03: "B with label")
    motifs = "const MOTIFS={bars:5,vu:0,"
    motifs_more = "const MOTIFS={wavefile:0,bars:5,vu:0,"
    family = "studio:['vu','eq','wave','knob','fader','rec','bars']"
    family_more = "studio:['vu','eq','wave','knob','fader','rec','bars','wavefile']"
    rec_route = " if(/print|bounce|export|render|record/.test(t))return 'rec';"
    file_route = (" if(/\\.wav\\b|\\.aiff?\\b|the final version|the corrected version|the song as it stands|the finished song|a link to/.test(t))return 'wavefile';\n"
                  + rec_route)
    vu_css = ".mk.vu svg{"
    wavefile_css = ".mk.wavefile{height:36px}.mk.wavefile svg{width:28px;height:36px}\n" + vu_css
    # Owner 2026-11-03: listening is its own moment. While Voice Transcribe runs, the mind shows "listening" and a
    # sound wave instead of a task line; when it ends, the words heard are typed out left to right, as the Now line is
    calling = "<span class=\"w\">calling</span><b>'+esc(m.name)+'</b></span><span class=\"clock\" data-clock=\"'+focus.startTs+'\"></span></div><div class=\"big\">'+esc(focus.task||'')+'<span class=\"caret\"></span></div>'"
    listening = ("<span class=\"w\">'+(focus.key==='musevoicetranscribe10'?'listening':'calling')+'</span><b>'+esc(m.name)+'</b></span><span class=\"clock\" data-clock=\"'+focus.startTs+'\"></span></div>'"
                 "+(focus.key==='musevoicetranscribe10'?'<div class=\"big ear\"><span class=\"bars\">'+'<i></i>'.repeat(11)+'</span></div>':'<div class=\"big\">'+esc(focus.task||'')+'<span class=\"caret\"></span></div>')")
    decided_line = "   cur.innerHTML='<div class=\"khd\"><span class=\"kind\"><span class=\"w\">'+lab+'</span><b>'+esc(m.name)+'</b></span>'+(took!=null?'<span class=\"clock final\">'+fmtClock(took)+'</span>':'')+'</div><div class=\"big\">'+esc(sum)+'</div>'+(focus.detail?'<div class=\"why\">'+esc(focus.detail)+'</div>':'')+proofHtml(focus);}"
    heard_line = ("   const heardKey=focus.key==='musevoicetranscribe10'?String(focus.id||'')+'|'+sum:'';if(heardKey&&cur.dataset.typed===heardKey){tick();return;}\n"
                  + decided_line[:-1] + "\n   if(heardKey){cur.dataset.typed=heardKey;typeInto(cur.querySelector('.big'),sum);}else{delete cur.dataset.typed;}}")
    type_now = "function renderNow(){"
    type_into = ("function typeInto(el,text){if(!el)return;el.innerHTML=[...text].map(ch=>'<span class=\"c\">'+esc(ch)+'</span>').join('')+'<span class=\"caret\"></span>';"
                 "const chars=el.querySelectorAll('.c'),caret=el.querySelector('.caret');let i=0;el.classList.add('typing');"
                 "(function step(){if(i>=chars.length){el.classList.remove('typing');return;}const ch=chars[i];ch.classList.add('on');ch.after(caret);i++;const c=ch.textContent;setTimeout(step,c===' '?55:/[.,]/.test(c)?140:22+Math.random()*26);})();}\n"
                 + type_now)
    ear_css = (".big.ear{display:flex;align-items:center;min-height:1.2em}.big.ear .bars{display:inline-flex;align-items:center;gap:10px;height:1em}"
               ".big.ear .bars i{display:block;width:12px;height:.3em;border-radius:6px;background:var(--accent);animation:ear 1.1s ease-in-out infinite}"
               + "".join(f".big.ear .bars i:nth-child({k+1}){{animation-delay:{(k*0.09)%0.7:.2f}s;animation-duration:{0.9+(k%4)*0.15:.2f}s}}" for k in range(11))
               + "@keyframes ear{0%,100%{height:.22em;opacity:.55}50%{height:1em;opacity:1}}"
               ".big.typing .c{opacity:0}.big .c.on{opacity:1}.big .caret{display:inline-block;width:.42em;height:.9em;margin-left:.1em;vertical-align:-.08em;background:var(--accent)}\n")
    if not (sample and links and styled and icon and tally in page and decided in page and using in page and shown in page
            and page.count(calling) == 1 and page.count(decided_line) == 1 and page.count(type_now) == 1 and page.count(decided_focus) == 1
            and page.count(run_start) == 1 and page.count(eq_mark) == 1 and page.count(motifs) == 1 and page.count(family) == 1
            and page.count(rec_route) == 1 and page.count(vu_css) == 1):
        raise SystemExit(f"the design changed shape: sample {sample}, fonts {links}, style {styled}, icon {icon}, tally {tally in page}, "
                         f"decided {decided in page}, using {using in page}, shown {shown in page}, run {page.count(run_start)}")
    # the mode's word on screen (the design carries it hidden): a replay must not pass as live; and the path keeps Deliver in
    # frame when a step back marks several stages
    extra = ".mode .mlabel{display:inline}.mode.replay .mlabel{color:var(--catch)}.mode.live .mlabel{color:var(--accent)}\n.banner #path{gap:0 14px}\n" + ear_css
    return (page.replace(tally, counted).replace(decided_focus, worded_focus, 1).replace(decided, worded).replace(using, testing).replace(shown, lit)
            .replace(run_start, run_reset).replace(eq_mark, wavefile_mark, 1).replace(motifs, motifs_more, 1)
            .replace(family, family_more, 1).replace(rec_route, file_route, 1).replace(vu_css, wavefile_css, 1)
            .replace(calling, listening, 1).replace(decided_line, heard_line, 1).replace(type_now, type_into, 1)
            .replace("</style>", extra + "</style>", 1))


if __name__ == "__main__":
    out = build((TRACE / "design.html").read_text())
    (TRACE / "index.html").write_text(out)
    print(f"{TRACE / 'index.html'}: {len(out)} characters, network references: {len(re.findall(r'https?://(?!www.w3.org)', out))}")
