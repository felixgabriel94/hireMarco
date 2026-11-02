// Logic's pop-up menu windows on screen right now (window layer 101), as [x, y, width, height] in screen points.
// The plug-in menu that opens on an insert slot is one of these: it is not in the accessibility tree, so it is
// driven by its bounds (mapped live 2026-11-02: a search field across its top, result rows below it).
ObjC.import("CoreGraphics");
const info = ObjC.castRefToObject($.CGWindowListCopyWindowInfo($.kCGWindowListOptionOnScreenOnly, $.kCGNullWindowID));
const out = [];
for (let i = 0; i < info.count; i++) {
  const w = info.objectAtIndex(i);
  if (ObjC.unwrap(w.objectForKey("kCGWindowOwnerName")) === "Logic Pro" && ObjC.unwrap(w.objectForKey("kCGWindowLayer")) === 101) {
    const b = w.objectForKey("kCGWindowBounds");
    out.push([ObjC.unwrap(b.objectForKey("X")), ObjC.unwrap(b.objectForKey("Y")), ObjC.unwrap(b.objectForKey("Width")), ObjC.unwrap(b.objectForKey("Height"))]);
  }
}
JSON.stringify(out);
