// Click the bypass checkbox of one insert on the Stereo Out strip in Logic's Mixer window, by the plugin's short
// name as the strip shows it and, when given, its vertical position (two inserts can share a name, live
// 2026-11-02: Gain twice). Prints the checkbox's value after the click ("true" bypassed, "false" in).
// Run: osascript -l JavaScript stereo_out_bypass.js "Gain" [y]
function run(argv) {
  const wanted = String(argv[0] || "");
  const wantedY = argv.length > 1 ? Number(argv[1]) : null;
  const se = Application("System Events");
  const logic = se.processes.byName("Logic Pro");
  function s(f) { try { const v = f(); return v === null || v === undefined ? "" : String(v); } catch (e) { return ""; } }
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
  const wins = logic.windows();
  let mixer = null;
  for (let i = 0; i < wins.length; i++) { if (s(() => wins[i].name()).indexOf("Mixer") >= 0) { mixer = wins[i]; break; } }
  if (mixer === null) throw new Error("no Mixer window");
  const groups = outputStrip(mixer).strip.groups();
  for (let i = 0; i < groups.length; i++) {
    if (s(() => groups[i].description()) !== wanted) continue;
    if (wantedY !== null && Math.abs(groups[i].position()[1] - wantedY) > 4) continue;
    const cbs = groups[i].checkboxes();
    for (let j = 0; j < cbs.length; j++) {
      if (s(() => cbs[j].description()) === "bypass") {
        cbs[j].click();
        delay(0.3);
        return s(() => cbs[j].value());
      }
    }
  }
  throw new Error("no insert named " + wanted + " on the Stereo Out");
}
