// Press the "list" button of one insert on the output strip in Logic's Mixer window (Single view), by the plugin's
// short name and its row, which opens that slot's own plug-in menu (mapped live 2026-11-02: search field focused,
// then the current plug-in's row, then "No Plug-in", then Recent and the categories). Prints "opened".
// Run: osascript -l JavaScript stereo_out_list.js "Kickstart " [y]
function run(argv) {
  const wanted = String(argv[0] || "");
  const wantedY = argv.length > 1 ? Number(argv[1]) : null;
  const se = Application("System Events");
  const logic = se.processes.byName("Logic Pro");
  function s(f) { try { const v = f(); return v === null || v === undefined ? "" : String(v); } catch (e) { return ""; } }
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
    return items[at];
  }
  const wins = logic.windows();
  let mixer = null;
  for (let i = 0; i < wins.length; i++) { if (s(() => wins[i].name()).indexOf("Mixer") >= 0) { mixer = wins[i]; break; } }
  if (mixer === null) throw new Error("no Mixer window");
  const groups = outputStrip(mixer).groups();
  for (let i = 0; i < groups.length; i++) {
    if (s(() => groups[i].description()) !== wanted) continue;
    if (wantedY !== null && Math.abs(groups[i].position()[1] - wantedY) > 4) continue;
    const kids = groups[i].uiElements();
    for (let j = 0; j < kids.length; j++) {
      if (s(() => kids[j].role()) === "AXButton" && s(() => kids[j].description()) === "list") {
        kids[j].actions.byName("AXPress").perform();
        delay(0.8);
        return "opened";
      }
    }
  }
  throw new Error("no insert named " + wanted + " on the output strip");
}
