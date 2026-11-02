// The session's layout, read only (live map 2026-11-02): every track header (its description "Track N “name”",
// its disclosure triangle when it is a stack, the x of its name for the indent), every lane's regions (description,
// x, width in screen points) including the global lanes (Arrangement, Marker), and the playhead thumb's x on the
// time ruler so a caller can turn x into bars from two known playhead positions. Prints JSON.
// Run: osascript -l JavaScript survey.js
const se = Application("System Events");
const logic = se.processes.byName("Logic Pro");
function s(f) { try { const v = f(); return v === null || v === undefined ? "" : String(v); } catch (e) { return ""; } }
const wins = logic.windows();
let tracks = null;
for (let i = 0; i < wins.length; i++) { if (s(() => wins[i].name()).endsWith(" - Tracks")) { tracks = wins[i]; break; } }
if (tracks === null) throw new Error("no Tracks window");
function findDesc(root, wanted, maxDepth) {
  let level = [root];
  for (let depth = 0; depth < maxDepth && level.length > 0; depth++) {
    const next = [];
    for (let i = 0; i < level.length; i++) {
      const el = level[i];
      const d = s(() => el.description());
      if (d === wanted) return el;
      if (d === "Inspector" || d === "Control Bar" || d === "Mixer" || d === "Library") continue;
      if (d.indexOf("Track ") === 0) continue;
      let kids = []; try { kids = el.uiElements(); } catch (e) { kids = []; }
      for (let j = 0; j < kids.length; j++) next.push(kids[j]);
    }
    level = next;
  }
  return null;
}
const header = findDesc(tracks, "Tracks header", 10);
const contents = findDesc(tracks, "Tracks contents", 10);
const ruler = findDesc(tracks, "Tracks time ruler", 10);
if (header === null || contents === null) throw new Error("no Tracks header or contents");
const out = { headers: [], lanes: [], thumb_x: null, ruler: null };
const hk = header.uiElements();
for (let i = 0; i < hk.length; i++) {
  const h = hk[i];
  if (s(() => h.role()) !== "AXLayoutItem") continue;
  const row = { desc: s(() => h.description()), y: h.position()[1], h: h.size()[1], triangle: null, name_x: null, focus: false };
  try { const kids = h.uiElements(); for (let j = 0; j < kids.length; j++) {
    const r = s(() => kids[j].role()), d = s(() => kids[j].description());
    if (r === "AXDisclosureTriangle") row.triangle = s(() => kids[j].value());
    if (r === "AXStaticText" && row.name_x === null) row.name_x = kids[j].position()[0];
    if (r === "AXRadioButton" && d === "Has Focus") row.focus = s(() => kids[j].value()) === "1";
  } } catch (e) {}
  out.headers.push(row);
}
const lk = contents.uiElements();
for (let i = 0; i < lk.length; i++) {
  const lane = lk[i];
  if (s(() => lane.role()) !== "AXLayoutArea") continue;
  const row = { desc: s(() => lane.description()), y: lane.position()[1], regions: [] };
  try { const items = lane.uiElements(); for (let j = 0; j < items.length; j++) {
    if (s(() => items[j].role()) !== "AXLayoutItem") continue;
    const p = items[j].position(), z = items[j].size();
    row.regions.push([s(() => items[j].description()), p[0], z[0]]);
  } } catch (e) {}
  out.lanes.push(row);
}
if (ruler !== null) {
  out.ruler = [ruler.position()[0], ruler.size()[0]];
  try { const rk = ruler.uiElements(); for (let j = 0; j < rk.length; j++) { if (s(() => rk[j].description()) === "Playhead thumb") out.thumb_x = rk[j].position()[0]; } } catch (e) {}
}
JSON.stringify(out);
