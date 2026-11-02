// Logic's Mixer window moved to the top left and made tall, so every insert on a strip is on screen: with seven
// inserts the strip's slots scrolled and the hidden rows could not be clicked (live 2026-11-02). Prints the
// window's position and size after the move. Run: osascript -l JavaScript mixer_window.js [width] [height]
function run(argv) {
  const width = argv.length > 0 ? Number(argv[0]) : 1024;
  const height = argv.length > 1 ? Number(argv[1]) : 900;
  const se = Application("System Events");
  const logic = se.processes.byName("Logic Pro");
  function s(f) { try { const v = f(); return v === null || v === undefined ? "" : String(v); } catch (e) { return ""; } }
  const wins = logic.windows();
  for (let i = 0; i < wins.length; i++) {
    if (s(() => wins[i].name()).indexOf("Mixer") < 0) continue;
    try { wins[i].position = [20, 44]; } catch (e) {}
    try { wins[i].size = [width, height]; } catch (e) {}
    return JSON.stringify({ position: wins[i].position(), size: wins[i].size() });
  }
  throw new Error("no Mixer window");
}
