// The Stereo Out strip in Logic's Mixer window, read only (mapped live 2026-11-02): its empty insert slot (the thin
// "audio plug-in" button under the last insert), its inserts top first (each a group described by the plugin's
// short name, with a bypass checkbox) and the mastering assistant button. Prints JSON:
//   {"slot": [x, y, w, h], "inserts": [[name, bypassed, x, y]], "assistant": [x, y, w, h]}
// Run: osascript -l JavaScript stereo_out.js
const se = Application("System Events");
const logic = se.processes.byName("Logic Pro");
function s(f) { try { const v = f(); return v === null || v === undefined ? "" : String(v); } catch (e) { return ""; } }
function find(el, depth, pred, out) {
  if (depth > 14) return;
  if (pred(el)) { out.push(el); return; }
  let kids = []; try { kids = el.uiElements(); } catch (e) { kids = []; }
  for (let i = 0; i < kids.length; i++) find(kids[i], depth + 1, pred, out);
}
const wins = logic.windows();
let mixer = null;
for (let i = 0; i < wins.length; i++) { if (s(() => wins[i].name()).indexOf("Mixer") >= 0) { mixer = wins[i]; break; } }
if (mixer === null) throw new Error("no Mixer window");
const strips = [];
find(mixer, 0, el => s(() => el.role()) === "AXLayoutItem" && s(() => el.description()) === "Stereo Out", strips);
if (strips.length === 0) throw new Error("no Stereo Out strip in the Mixer window");
const strip = strips[0];
const result = { slot: null, inserts: [], assistant: null };
const buttons = strip.buttons();
for (let i = 0; i < buttons.length; i++) {
  const b = buttons[i];
  const d = s(() => b.description());
  const p = b.position(), z = b.size();
  if (d === "audio plug-in" && z[1] < 12 && result.slot === null) result.slot = [p[0], p[1], z[0], z[1]];
  if (d === "mastering assistant") result.assistant = [p[0], p[1], z[0], z[1]];
}
const groups = strip.groups();
for (let i = 0; i < groups.length; i++) {
  const g = groups[i];
  let bypass = "";
  try { const cbs = g.checkboxes(); for (let j = 0; j < cbs.length; j++) { if (s(() => cbs[j].description()) === "bypass") bypass = s(() => cbs[j].value()); } } catch (e) {}
  if (bypass === "") continue;
  const p = g.position();
  result.inserts.push([s(() => g.description()), bypass === "true" || bypass === "1", p[0], p[1]]);
}
result.inserts.sort((a, b) => a[3] - b[3]);
JSON.stringify(result);
