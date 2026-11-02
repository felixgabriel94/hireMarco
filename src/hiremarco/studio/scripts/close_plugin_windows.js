// Close every plug-in window Logic opened (any window that is not the Tracks window or the Mixer window), by the
// button described "close" at its top left (read live 2026-11-02). Prints how many were closed. An AppleScript
// "click" on the same button hung once for a minute; the JavaScript click returns.
const se = Application("System Events");
const logic = se.processes.byName("Logic Pro");
function s(f) { try { const v = f(); return v === null || v === undefined ? "" : String(v); } catch (e) { return ""; } }
let n = 0;
const wins = logic.windows();
for (let i = 0; i < wins.length; i++) {
  const name = s(() => wins[i].name());
  if (name.indexOf(" - Tracks") >= 0 || name.indexOf("Mixer") >= 0) continue;
  try {
    const buttons = wins[i].buttons.whose({ description: "close" })();
    if (buttons.length) { buttons[0].click(); n++; }
  } catch (e) {}
}
String(n);
