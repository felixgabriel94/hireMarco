// The Tracks area's vertical scroll bar set in one move (0 top, 1 bottom), so a track header can be reached
// without a mouse wheel (which scrolls whatever sits under the pointer, live 2026-11-02) and without ticks. The
// scroll bar's index path from the Tracks window is cached in the state folder after the first search, so a
// later call walks straight to it (the breadth-first search cost 30 s on a forty-track session); a cached path
// that no longer lands on a vertical scroll bar is searched again. Prints the value after the move.
// Run: osascript -l JavaScript tracks_scroll_top.js [value]
ObjC.import("Foundation");
function run(argv) {
  const wanted = argv.length > 0 ? Number(argv[0]) : 0;
  const se = Application("System Events");
  const logic = se.processes.byName("Logic Pro");
  function s(f) { try { const v = f(); return v === null || v === undefined ? "" : String(v); } catch (e) { return ""; } }
  const wins = logic.windows();
  let tracks = null;
  for (let i = 0; i < wins.length; i++) { if (s(() => wins[i].name()).endsWith(" - Tracks")) { tracks = wins[i]; break; } }
  if (tracks === null) throw new Error("no Tracks window");
  const home = $.NSHomeDirectory().js;
  const cache = home + "/.local/state/hiremarco/tracks_scrollbar.path";
  function isVertical(el) { return s(() => el.role()) === "AXScrollBar" && s(() => el.orientation()) === "AXVerticalOrientation"; }
  function walk(path) {
    let el = tracks;
    for (let i = 0; i < path.length; i++) {
      let kids = []; try { kids = el.uiElements(); } catch (e) { return null; }
      if (path[i] >= kids.length) return null;
      el = kids[path[i]];
    }
    return el;
  }
  let best = null;
  try {
    const text = $.NSString.stringWithContentsOfFileEncodingError(cache, $.NSUTF8StringEncoding, null);
    if (text && text.js) {
      const path = text.js.trim().split(",").map(Number);
      const el = walk(path);
      if (el !== null && isVertical(el) && el.size()[1] > 100) best = el;
    }
  } catch (e) {}
  if (best === null) {
    const skip = { "Inspector": 1, "Control Bar": 1, "Library": 1, "Mixer": 1, "Tracks header": 1, "Tracks contents": 1, "Tracks time ruler": 1 };
    let bestHeight = 0, bestPath = null;
    let level = [[tracks, []]];
    for (let depth = 0; depth < 9 && level.length > 0; depth++) {
      const next = [];
      for (let i = 0; i < level.length; i++) {
        const el = level[i][0], path = level[i][1];
        const role = s(() => el.role()), d = s(() => el.description());
        if (skip[d] || d.indexOf("Track ") === 0) continue;
        if (role === "AXScrollBar") {
          if (s(() => el.orientation()) === "AXVerticalOrientation") { const h = el.size()[1]; if (h > bestHeight) { best = el; bestHeight = h; bestPath = path; } }
          continue;
        }
        if (role === "AXLayoutArea" || role === "AXTable" || role === "AXList") continue;
        let kids = []; try { kids = el.uiElements(); } catch (e) { kids = []; }
        for (let j = 0; j < kids.length; j++) next.push([kids[j], path.concat([j])]);
      }
      level = next;
    }
    if (best === null) throw new Error("no vertical scroll bar in the Tracks window");
    try { $.NSString.stringWithString(bestPath.join(",")).writeToFileAtomicallyEncodingError(cache, true, $.NSUTF8StringEncoding, null); } catch (e) {}
  }
  if (Number(s(() => best.value())) !== wanted) { best.value = wanted; delay(0.5); }
  return s(() => best.value());
}
