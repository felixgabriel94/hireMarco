// Used by live.py and show.py. Prints the window number of Logic Pro's largest on-screen normal window (layer 0),
// the main window, or nothing when Logic has none. Window names need Screen Recording, so the size picks it.
ObjC.import("CoreGraphics");
const info = ObjC.castRefToObject($.CGWindowListCopyWindowInfo($.kCGWindowListOptionOnScreenOnly, $.kCGNullWindowID));
let best = "", area = 0;
for (let i = 0; i < info.count; i++) {
  const w = info.objectAtIndex(i);
  const owner = ObjC.unwrap(w.objectForKey("kCGWindowOwnerName"));
  const layer = ObjC.unwrap(w.objectForKey("kCGWindowLayer"));
  if (owner !== "Logic Pro" || layer !== 0) continue;
  const b = ObjC.deepUnwrap(w.objectForKey("kCGWindowBounds"));
  if (b.Width * b.Height > area) { area = b.Width * b.Height; best = String(ObjC.unwrap(w.objectForKey("kCGWindowNumber"))); }
}
best;
