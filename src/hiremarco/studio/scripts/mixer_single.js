// Logic's Mixer window in Single view: the selected track's signal flow, a handful of strips ending at the output,
// so the output strip is on screen whatever the session's size (a Tracks view of forty strips left it off screen
// with its description blank, live 2026-11-02). Prints the strip names in order. Run: osascript -l JavaScript mixer_single.js
const se = Application("System Events");
const logic = se.processes.byName("Logic Pro");
function s(f) { try { const v = f(); return v === null || v === undefined ? "" : String(v); } catch (e) { return ""; } }
const wins = logic.windows();
let mixer = null;
for (let i = 0; i < wins.length; i++) { if (s(() => wins[i].name()).indexOf("Mixer") >= 0) { mixer = wins[i]; break; } }
if (mixer === null) throw new Error("no Mixer window");
// breadth first, by role and description, never by a child's index: the window's tree shifted once it moved to
// the 4K display and the indexed path found nothing (live 2026-11-02)
function firstWhere(root, pred, maxDepth) {
  let level = [root];
  for (let depth = 0; depth < maxDepth && level.length > 0; depth++) {
    const next = [];
    for (let i = 0; i < level.length; i++) {
      const el = level[i];
      if (pred(el)) return el;
      const role = s(() => el.role());
      if (role === "AXLayoutArea" || role === "AXLayoutItem") continue;
      let kids = []; try { kids = el.uiElements(); } catch (e) { kids = []; }
      for (let j = 0; j < kids.length; j++) next.push(kids[j]);
    }
    level = next;
  }
  return null;
}
// a narrow Mixer window folds its toolbar into an overflow menu and the view buttons go with it (live 2026-11-02:
// 440 wide on the 4K display, three toolbar items left); the window is widened to 1024 in place, moved left
// inside the display it sits on (the Tracks window's span stands for the display) when there is no room
let single = firstWhere(mixer, el => s(() => el.role()) === "AXRadioButton" && s(() => el.description()) === "Single", 8);
if (single === null) {
  let tracks = null;
  for (let i = 0; i < wins.length; i++) { if (s(() => wins[i].name()).endsWith(" - Tracks")) { tracks = wins[i]; break; } }
  const want = 1024, pos = mixer.position(), size = mixer.size();
  let x = pos[0];
  if (tracks !== null) { const right = tracks.position()[0] + tracks.size()[0]; if (x + want > right) x = Math.max(tracks.position()[0], right - want); }
  try { mixer.position = [x, pos[1]]; } catch (e) {}
  try { mixer.size = [want, size[1]]; } catch (e) {}
  delay(0.8);
  single = firstWhere(mixer, el => s(() => el.role()) === "AXRadioButton" && s(() => el.description()) === "Single", 8);
}
if (single === null) throw new Error("no Single view button in the Mixer window (" + mixer.size() + " wide)");
if (s(() => single.value()) !== "1") { single.click(); delay(0.8); }
if (s(() => single.value()) !== "1") throw new Error("the Mixer did not switch to Single view");
const area = firstWhere(mixer, el => s(() => el.role()) === "AXLayoutArea", 8);
if (area === null) throw new Error("no strip area in the Mixer window");
const items = area.uiElements();
const names = [];
for (let i = 0; i < items.length; i++) names.push(s(() => items[i].description()));
JSON.stringify(names);
