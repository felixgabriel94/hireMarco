// Every closed track stack in the Tracks header opened, nested ones too, so the survey sees the member tracks
// (live 2026-11-04: with the stacks closed the organizer saw 3 of 30 tracks and said the session was labeled).
// Clicks only disclosure triangles that read 0; a few passes for stacks inside stacks. Prints JSON.
// Run: osascript -l JavaScript open_stacks.js
const se = Application("System Events");
const logic = se.processes.byName("Logic Pro");
function s(f) { try { const v = f(); return v === null || v === undefined ? "" : String(v); } catch (e) { return ""; } }
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
const wins = logic.windows();
let tracks = null;
for (let i = 0; i < wins.length; i++) { if (s(() => wins[i].name()).endsWith(" - Tracks")) { tracks = wins[i]; break; } }
if (tracks === null) throw new Error("no Tracks window");
let opened = 0, closed = 0;
for (let pass = 0; pass < 40; pass++) {   // one stack a pass; the rows move once it opens
  const header = findDesc(tracks, "Tracks header", 10);
  if (header === null) throw new Error("no Tracks header");
  const hk = header.uiElements();
  closed = 0;
  let clicked = 0;
  for (let i = 0; i < hk.length; i++) {
    if (s(() => hk[i].role()) !== "AXLayoutItem") continue;
    let kids = []; try { kids = hk[i].uiElements(); } catch (e) { kids = []; }
    for (let j = 0; j < kids.length; j++) {
      if (s(() => kids[j].role()) !== "AXDisclosureTriangle" || s(() => kids[j].value()) !== "0") continue;
      closed++;
      try { kids[j].actions["AXPress"].perform(); clicked++; }
      catch (e) { try { se.click(kids[j]); clicked++; } catch (e2) {} }
      delay(0.3);
      break;
    }
    if (clicked > 0) break;   // the rows move once a stack opens: read the header again
  }
  opened += clicked;
  if (clicked === 0) break;
  delay(0.4);
}
JSON.stringify({ opened: opened, still_closed: closed });
