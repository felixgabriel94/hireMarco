// Logic's Mixer window made tall, so every insert on a strip is on screen: with seven inserts the strip's slots
// scrolled and the hidden rows could not be clicked (live 2026-11-02). The window stays on the display it sits on
// (the Owner's TV or the laptop, his choice) and is sized to fit that display: a size taken from another window's
// display squashed it to 400 points and the insert rows scrolled above the window (live 2026-11-02, run 22).
// Prints the window's position and size after the move. Run: osascript -l JavaScript mixer_window.js [width] [height]
ObjC.import("AppKit");
function run(argv) {
  const wantWidth = argv.length > 0 ? Number(argv[0]) : 1024;
  const wantHeight = argv.length > 1 ? Number(argv[1]) : 900;
  const se = Application("System Events");
  const logic = se.processes.byName("Logic Pro");
  function s(f) { try { const v = f(); return v === null || v === undefined ? "" : String(v); } catch (e) { return ""; } }
  // the displays in Accessibility's frame (origin top left of the main display): Cocoa's frames flipped
  const screens = $.NSScreen.screens;
  const mainH = screens.objectAtIndex(0).frame.size.height;
  const displays = [];
  for (let i = 0; i < screens.count; i++) {
    const f = screens.objectAtIndex(i).frame;
    displays.push({ left: f.origin.x, top: mainH - (f.origin.y + f.size.height), width: f.size.width, height: f.size.height });
  }
  const wins = logic.windows();
  for (let i = 0; i < wins.length; i++) {
    if (s(() => wins[i].name()).indexOf("Mixer") < 0) continue;
    const pos = wins[i].position();
    let display = displays[0];
    for (let d = 0; d < displays.length; d++) {
      const dd = displays[d];
      if (pos[0] >= dd.left && pos[0] < dd.left + dd.width && pos[1] >= dd.top && pos[1] < dd.top + dd.height) display = dd;
    }
    const top = display.top + 24;                       // under the menu bar
    const width = Math.min(wantWidth, display.width);
    const height = Math.min(wantHeight, display.height - 24 - 80);   // room for the Dock
    let x = pos[0], y = Math.max(pos[1], top);
    if (x + width > display.left + display.width) x = Math.max(display.left, display.left + display.width - width);
    if (y + height > display.top + display.height - 80) y = Math.max(top, display.top + display.height - 80 - height);
    try { wins[i].position = [x, y]; } catch (e) {}
    try { wins[i].size = [width, height]; } catch (e) {}
    return JSON.stringify({ position: wins[i].position(), size: wins[i].size(), display: display });
  }
  throw new Error("no Mixer window");
}
