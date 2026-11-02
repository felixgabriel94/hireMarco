// The Tracks area scrolled to its top, so the first tracks' headers are on screen and can be clicked (live
// 2026-11-02: in a forty-track session the BEAT header sat at y = -1092, scrolled away above the window). The
// Tracks area's own vertical scroll bar is the tall one on the window's right; its value goes to 0. Prints the
// value after the move. Run: osascript -l JavaScript tracks_scroll_top.js [value]   (0 top, 1 bottom; default 0)
function run(argv) {
const wanted = argv.length > 0 ? Number(argv[0]) : 0;
const se = Application("System Events");
const logic = se.processes.byName("Logic Pro");
function s(f) { try { const v = f(); return v === null || v === undefined ? "" : String(v); } catch (e) { return ""; } }
const wins = logic.windows();
let tracks = null;
for (let i = 0; i < wins.length; i++) { if (s(() => wins[i].name()).endsWith(" - Tracks")) { tracks = wins[i]; break; } }
if (tracks === null) throw new Error("no Tracks window");
let best = null, bestHeight = 0;
let level = [tracks];
for (let depth = 0; depth < 9 && level.length > 0; depth++) {
  const next = [];
  for (let i = 0; i < level.length; i++) {
    const el = level[i];
    const role = s(() => el.role());
    if (role === "AXScrollBar") {
      if (s(() => el.orientation()) === "AXVerticalOrientation") { const h = el.size()[1]; if (h > bestHeight) { best = el; bestHeight = h; } }
      continue;
    }
    if (role === "AXLayoutArea" || role === "AXTable" || role === "AXList") continue;
    let kids = []; try { kids = el.uiElements(); } catch (e) { kids = []; }
    for (let j = 0; j < kids.length; j++) next.push(kids[j]);
  }
  level = next;
}
if (best === null) throw new Error("no vertical scroll bar in the Tracks window");
if (Number(s(() => best.value())) !== wanted) { best.value = wanted; delay(0.5); }
return s(() => best.value());
}
