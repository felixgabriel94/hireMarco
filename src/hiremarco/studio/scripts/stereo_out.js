// The Stereo Out strip in Logic's Mixer window, read only (mapped live 2026-11-02): its empty insert slot (the thin
// "audio plug-in" button under the last insert), its inserts top first (each a group described by the plugin's
// short name, with a bypass checkbox) and the mastering assistant button. Prints JSON:
//   {"name": "Stereo Out", "slot": [x, y, w, h], "inserts": [[name, bypassed, x, y]], "assistant": [x, y, w, h]}
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
// The output strip (the Stereo Out, whatever the artist named it: "FG Master" in one session, live 2026-11-02):
// breadth first to the strip area, then its direct children only, since a depth-first walk read every element of
// every strip and took over a minute on a forty-track session. By the name "Stereo Out" first, else the strip
// before the Master fader, else the last strip. The Mixer is kept in Single view, where the selected track's
// signal flow ends at the output, so the strip is on screen and its description populated.
function layoutArea(root) {
  let level = [root];
  for (let depth = 0; depth < 14 && level.length > 0; depth++) {
    const next = [];
    for (let i = 0; i < level.length; i++) {
      const el = level[i];
      if (s(() => el.role()) === "AXLayoutArea") return el;
      let kids = []; try { kids = el.uiElements(); } catch (e) { kids = []; }
      for (let j = 0; j < kids.length; j++) next.push(kids[j]);
    }
    level = next;
  }
  return null;
}
function outputStrip(mixer) {
  const area = layoutArea(mixer);
  if (area === null) throw new Error("no strip area in the Mixer window");
  const items = area.uiElements();
  const names = [];
  for (let i = 0; i < items.length; i++) names.push(s(() => items[i].role()) === "AXLayoutItem" ? s(() => items[i].description()) : "");
  let at = names.indexOf("Stereo Out");
  if (at < 0 && names.indexOf("Master") > 0) at = names.indexOf("Master") - 1;
  if (at < 0) at = names.length - 1;
  if (at < 0) throw new Error("no strips in the Mixer window");
  return { strip: items[at], name: names[at] };
}
const found = outputStrip(mixer);
const strip = found.strip;
const result = { name: found.name, slot: null, inserts: [], assistant: null };
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
