// Used by load_preset.applescript. Prints how many pop-up menu windows (window layer 101) Logic Pro has on screen right now.
ObjC.import("CoreGraphics");
const info = ObjC.castRefToObject($.CGWindowListCopyWindowInfo($.kCGWindowListOptionOnScreenOnly, $.kCGNullWindowID));
let n = 0;
for (let i = 0; i < info.count; i++) {
  const w = info.objectAtIndex(i);
  const owner = ObjC.unwrap(w.objectForKey("kCGWindowOwnerName"));
  const layer = ObjC.unwrap(w.objectForKey("kCGWindowLayer"));
  if (owner === "Logic Pro" && layer === 101) n++;
}
String(n);
