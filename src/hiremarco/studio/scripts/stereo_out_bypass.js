// Click the bypass checkbox of one insert on the Stereo Out strip in Logic's Mixer window, by the plugin's short
// name as the strip shows it. Prints the checkbox's value after the click ("true" bypassed, "false" in).
// Run: osascript -l JavaScript stereo_out_bypass.js "Gain"
function run(argv) {
  const wanted = String(argv[0] || "");
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
  const groups = strips[0].groups();
  for (let i = 0; i < groups.length; i++) {
    if (s(() => groups[i].description()) !== wanted) continue;
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
