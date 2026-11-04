// Only the track headers, read only: each row's description, its stack triangle and the x of its name (the indent
// shows what sits inside a stack). The quick part of survey.js, for placing a new track inside its stack (2026-11-04).
// Was: The session's layout, read only (live map 2026-11-02): every track header (its description "Track N “name”",
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
const out = [];
if (header === null) throw new Error("no Tracks header");
const hk = header.uiElements();
for (let i = 0; i < hk.length; i++) {
  const h = hk[i];
  if (s(() => h.role()) !== "AXLayoutItem") continue;
  const row = { desc: s(() => h.description()), triangle: null, name_x: null };
  try { const kids = h.uiElements(); for (let j = 0; j < kids.length; j++) {
    const r = s(() => kids[j].role());
    if (r === "AXDisclosureTriangle") row.triangle = s(() => kids[j].value());
    if (r === "AXStaticText" && row.name_x === null) row.name_x = kids[j].position()[0];
  } } catch (e) {}
  out.push(row);
}
JSON.stringify(out);
