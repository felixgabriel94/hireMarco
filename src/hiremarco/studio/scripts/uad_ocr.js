// Text on a window capture, recognized on this Mac by Apple's Vision framework: no model call, about
// 0.6 s for a 1048 x 1200 capture (live 2026-11-02). Prints JSON rows {y, x, w, h, text, conf} in capture
// pixels, top to bottom then left to right. Usage: osascript -l JavaScript uad_ocr.js capture.png
ObjC.import('Foundation'); ObjC.import('Vision'); ObjC.import('CoreGraphics'); ObjC.import('ImageIO');
function run(argv) {
  const path = argv[0];
  const url = $.NSURL.fileURLWithPath(path);
  const src = $.CGImageSourceCreateWithURL(url, null);
  const img = $.CGImageSourceCreateImageAtIndex(src, 0, null);
  const W = $.CGImageGetWidth(img), H = $.CGImageGetHeight(img);
  const req = $.VNRecognizeTextRequest.alloc.init;
  req.recognitionLevel = $.VNRequestTextRecognitionLevelAccurate;
  req.usesLanguageCorrection = false;
  const h = $.VNImageRequestHandler.alloc.initWithCGImageOptions(img, $.NSDictionary.dictionary);
  const err = Ref();
  const ok = h.performRequestsError($.NSArray.arrayWithObject(req), err);
  const out = [];
  const res = req.results;
  for (let i = 0; i < res.count; i++) {
    const o = res.objectAtIndex(i);
    const c = o.topCandidates(1).objectAtIndex(0);
    const b = o.boundingBox;
    out.push({y: Math.round((1 - b.origin.y - b.size.height) * H), x: Math.round(b.origin.x * W),
              w: Math.round(b.size.width * W), h: Math.round(b.size.height * H), text: ObjC.unwrap(c.string), conf: Math.round(c.confidence * 100) / 100});
  }
  out.sort((a, b) => a.y - b.y || a.x - b.x);
  return JSON.stringify({ok: ok, W: W, H: H, rows: out});
}
