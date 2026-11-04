"""Marco Live's page is built from the Owner's design by string replacements; each one must still find its place."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("build_live_page", ROOT / "scripts" / "build_live_page.py")
build_live_page = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_live_page)


def test_the_page_builds_from_the_design_with_the_listening_moment():
    page = build_live_page.build((ROOT / "src" / "hiremarco" / "trace" / "design.html").read_text())
    assert "function typeInto(" in page and "typeInto(cur.querySelector('.big'),sum)" in page
    assert "?'listening':'calling'" in page and '"big ear"' in page and "@keyframes ear" in page
    assert "sl.classList.add('ear')" in page and "bars.style.width" in page and ".sl.ear .sh b{overflow:visible" in page
    assert "function similar(" in page and "similar(slots[k],l)" in page
    assert "wd('listening','use')" in page and '"st ear"' in page and "data-heard" in page and "S.typedHeard" in page and "function earBars(" in page
    assert page.count("heardKey") >= 3 and "https://" not in page.replace("http://www.w3.org", "")
    import re
    import subprocess

    script = re.findall(r"<script>([\s\S]*?)</script>", page)[0]
    done = subprocess.run(["node", "--check", "-"], input=script, text=True, capture_output=True)   # the page's one script parses
    assert done.returncode == 0, done.stderr[-400:]
    assert "(focus.word||'done')))" in page and "(l.word||'done')))" in page
