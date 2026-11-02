// Logic's Mixer window moved to the top left and made tall, so every insert on a strip is on screen: with seven
// inserts the strip's slots scrolled and the hidden rows could not be clicked (live 2026-11-02). Prints the
// window's position and size after the move. Run: osascript -l JavaScript mixer_window.js [width] [height]
function run(argv) {
  const width = argv.length > 0 ? Number(argv[0]) : 1024;
  let height = argv.length > 1 ? Number(argv[1]) : 900;
  const se = Application("System Events");
  const logic = se.processes.byName("Logic Pro");
  function s(f) { try { const v = f(); return v === null || v === undefined ? "" : String(v); } catch (e) { return ""; } }
  const wins = logic.windows();
  for (let i = 0; i < wins.length; i++) {
    if (s(() => wins[i].name()).indexOf("Mixer") < 0) continue;
    // the window stays on the display the Owner put it on (his TV, live 2026-11-02): only resized in place, and
    // moved left inside that display when the width would run past its right edge, which the Tracks window's span
    // stands for
    const pos = wins[i].position();
    let x = pos[0], y = pos[1];
    for (let j = 0; j < wins.length; j++) {
      if (s(() => wins[j].name()).endsWith(" - Tracks")) {
        const tp = wins[j].position(), ts = wins[j].size();
        if (x + width > tp[0] + ts[0]) x = Math.max(tp[0], tp[0] + ts[0] - width);
        if (y < tp[1]) y = tp[1];
        if (y + height > tp[1] + ts[1]) height = Math.max(400, tp[1] + ts[1] - y);
      }
    }
    try { wins[i].position = [x, y]; } catch (e) {}
    try { wins[i].size = [width, height]; } catch (e) {}
    return JSON.stringify({ position: wins[i].position(), size: wins[i].size() });
  }
  throw new Error("no Mixer window");
}
