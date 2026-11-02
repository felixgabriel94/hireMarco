// Press the "open" button of one insert on the output strip in Logic's Mixer window (Single view), by the plugin's
// short name and its row, so its own window opens (named after the strip) and its face can be read. Prints
// "opened". Run: osascript -l JavaScript stereo_out_open.js "Pro-L 2" 420
function run(argv) {
  const wanted = String(argv[0] || ""), wantedY = Number(argv[1]);
  const se = Application("System Events"); const logic = se.processes.byName("Logic Pro");
  function s(f) { try { const v = f(); return v === null || v === undefined ? "" : String(v); } catch (e) { return ""; } }
  const wins = logic.windows(); let mixer = null;
  for (let i = 0; i < wins.length; i++) { if (s(() => wins[i].name()).indexOf("Mixer") >= 0) { mixer = wins[i]; break; } }
  function layoutArea(root) { let level = [root]; for (let d = 0; d < 14 && level.length > 0; d++) { const next = []; for (let i = 0; i < level.length; i++) { const el = level[i]; if (s(() => el.role()) === "AXLayoutArea") return el; let kids = []; try { kids = el.uiElements(); } catch (e) {} for (let j = 0; j < kids.length; j++) next.push(kids[j]); } level = next; } return null; }
  const items = layoutArea(mixer).uiElements(); const names = []; for (let i = 0; i < items.length; i++) names.push(s(() => items[i].description()));
  const at = names.indexOf("Master") > 0 ? names.indexOf("Master") - 1 : names.length - 1;
  const groups = items[at].groups();
  for (let i = 0; i < groups.length; i++) { if (s(() => groups[i].description()) !== wanted || Math.abs(groups[i].position()[1] - wantedY) > 4) continue;
    const kids = groups[i].uiElements(); for (let j = 0; j < kids.length; j++) if (s(() => kids[j].role()) === "AXButton" && s(() => kids[j].description()) === "open") { kids[j].actions.byName("AXPress").perform(); delay(2.5); return "opened"; } }
  throw new Error("no insert " + wanted);
}
