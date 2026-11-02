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
let single = null;
const groups = mixer.uiElements()[5].uiElements()[0].radioGroups();
for (let i = 0; i < groups.length; i++) {
  const rb = groups[i].radioButtons();
  for (let j = 0; j < rb.length; j++) { if (s(() => rb[j].description()) === "Single") single = rb[j]; }
}
if (single === null) throw new Error("no Single view button in the Mixer window");
if (s(() => single.value()) !== "1") { single.click(); delay(0.8); }
if (s(() => single.value()) !== "1") throw new Error("the Mixer did not switch to Single view");
const items = mixer.uiElements()[5].uiElements()[1].uiElements();
const names = [];
for (let i = 0; i < items.length; i++) names.push(s(() => items[i].description()));
JSON.stringify(names);
