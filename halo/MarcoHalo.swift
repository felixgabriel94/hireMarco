// Marco's halo: a floating orb over Logic that shows when he listens, thinks and speaks.
//
// A borderless, transparent window above other apps; clicks pass through to Logic. It centers itself on Logic's
// main window (the largest normal window Logic has on screen) and follows it. The booth sends its state over UDP
// on 127.0.0.1:8789, one line per message: "listening 0.12", "thinking 0", "speaking 0.6", "idle 0", "quit".
// Four seconds without a message and it closes itself, so a booth that dies never leaves it on screen.
// The number is a level from 0 to 1 (the artist's voice while listening, Marco's while speaking).
//
//   MarcoHalo                 run, waiting for the booth
//   MarcoHalo --preview DIR   write one picture per state to DIR and exit
import AppKit
import Network
import SwiftUI

final class HaloState: ObservableObject {
    @Published var mode = "idle"
    var target: Double = 0
    var level: Double = 0
}

let state = HaloState()

struct Orb: View {
    @ObservedObject var halo: HaloState
    var frozenTime: Double? = nil

    let deep = Color(red: 0.05, green: 0.18, blue: 0.85)
    let sky = Color(red: 0.42, green: 0.72, blue: 1.0)
    let ice = Color(red: 0.86, green: 0.94, blue: 1.0)

    var body: some View {
        TimelineView(.animation) { timeline in
            let t = frozenTime ?? timeline.date.timeIntervalSinceReferenceDate
            orb(at: t)
        }
    }

    func orb(at t: Double) -> some View {
        // ease the level toward the latest one the booth sent, so the orb moves smoothly between messages
        if frozenTime == nil { halo.level += (halo.target - halo.level) * 0.18 }
        let level = min(max(halo.level, 0), 1)
        let mode = halo.mode
        let speed = mode == "thinking" ? 3.2 : (mode == "speaking" ? 2.0 : 0.9)
        let breathe = 1 + 0.025 * sin(t * 1.3)
        let scale = breathe + (mode == "speaking" ? 0.08 : 0.03) * level
        let light = mode == "listening" ? 0.55 + 0.45 * level : (mode == "speaking" ? 0.7 + 0.3 * level : 0.6)
        let swell = mode == "speaking" ? 6 + 26 * level : (mode == "thinking" ? 10 : 4 + 8 * level)
        let w = 180.0, h = 142.0
        return ZStack {
            // a soft blue light under him, on whatever is behind
            Ellipse()
                .fill(RadialGradient(colors: [sky.opacity(0.30 * light), deep.opacity(0.18 * light), .clear],
                                     center: .center, startRadius: 0, endRadius: 112))
                .frame(width: 225, height: 172)
                .offset(y: 30)
                .blur(radius: 22)
            // the glass: dark inside, a faint blue at the bottom where the light pools
            Ellipse()
                .fill(LinearGradient(colors: [.black.opacity(0.72), Color(red: 0.02, green: 0.05, blue: 0.16).opacity(0.62),
                                              deep.opacity(0.30)],
                                     startPoint: .top, endPoint: .bottom))
                .frame(width: w, height: h)
            // the ribbon of light across the middle: white at its core, sky blue, then deep blue at the edges
            Canvas { ctx, size in
                let mid = size.height * 0.50
                func ribbon(_ phase: Double, _ amp: Double) -> Path {
                    var path = Path()
                    for i in 0...80 {
                        let u = Double(i) / 80
                        let x = u * size.width
                        let envelope = sin(u * .pi)  // calm at the rim, alive in the middle
                        let y = mid + envelope * (amp * sin(u * 2.4 * .pi + phase) + 0.4 * amp * sin(u * 5 * .pi - phase * 1.3))
                        i == 0 ? path.move(to: CGPoint(x: x, y: y)) : path.addLine(to: CGPoint(x: x, y: y))
                    }
                    return path
                }
                let phase = t * speed
                let across = Gradient(colors: [deep.opacity(0.0), deep, sky, ice, .white, ice, sky, deep, deep.opacity(0.0)])
                let shade = GraphicsContext.Shading.linearGradient(across, startPoint: .zero,
                                                                   endPoint: CGPoint(x: size.width, y: 0))
                var glow = ctx
                glow.addFilter(.blur(radius: 12))
                glow.opacity = 0.75 * light
                glow.stroke(ribbon(phase, swell), with: .color(deep), lineWidth: 26)
                var band = ctx
                band.addFilter(.blur(radius: 4))
                band.opacity = light
                band.stroke(ribbon(phase + 0.2, swell * 0.92), with: shade, lineWidth: 9)
                var core = ctx
                core.addFilter(.blur(radius: 0.8))
                core.opacity = light
                core.stroke(ribbon(phase + 0.35, swell * 0.85), with: shade, lineWidth: 2.5)
                var shimmer = ctx
                shimmer.addFilter(.blur(radius: 1.5))
                shimmer.opacity = 0.55 * light
                shimmer.stroke(ribbon(phase * 1.15 + 1.1, swell * 0.6), with: shade, lineWidth: 1.5)
            }
            .frame(width: w, height: h)
            .blendMode(.plusLighter)
            .mask(Ellipse().frame(width: w - 4, height: h - 4))
            // the rim: a thin edge of light, brightest at the top, and a glow pooling at the bottom
            Ellipse()
                .strokeBorder(LinearGradient(colors: [.white.opacity(0.55), sky.opacity(0.10), sky.opacity(0.45)],
                                             startPoint: .top, endPoint: .bottom), lineWidth: 1.2)
                .frame(width: w, height: h)
            Ellipse()
                .fill(RadialGradient(colors: [ice.opacity(0.35 * light), .clear], center: .center,
                                     startRadius: 0, endRadius: 52))
                .frame(width: 120, height: 30)
                .offset(y: h / 2 - 16)
                .blur(radius: 10)
                .blendMode(.plusLighter)
        }
        .scaleEffect(scale)
        .opacity(mode == "idle" ? 0.0 : 1.0)
        .animation(.easeInOut(duration: 0.6), value: mode)
        .frame(width: 300, height: 300)
    }

}

func logicFrame() -> CGRect? {
    guard let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as? [[String: Any]] else {
        return nil
    }
    var best: CGRect? = nil
    for info in list where (info[kCGWindowOwnerName as String] as? String) == "Logic Pro"
        && (info[kCGWindowLayer as String] as? Int) == 0 {
        guard let b = info[kCGWindowBounds as String] as? [String: CGFloat] else { continue }
        let r = CGRect(x: b["X"] ?? 0, y: b["Y"] ?? 0, width: b["Width"] ?? 0, height: b["Height"] ?? 0)
        if r.width * r.height > (best.map { $0.width * $0.height } ?? 0) { best = r }
    }
    return best
}

func listen() {
    let params = NWParameters.udp
    params.requiredLocalEndpoint = NWEndpoint.hostPort(host: "127.0.0.1", port: 8789)
    guard let listener = try? NWListener(using: params) else {
        FileHandle.standardError.write("halo: port 8789 is taken\n".data(using: .utf8)!)
        exit(1)
    }
    listener.newConnectionHandler = { conn in
        conn.start(queue: .main)
        func next() {
            conn.receiveMessage { data, _, _, _ in
                lastHeard = Date()
                if let data, let line = String(data: data, encoding: .utf8) {
                    let parts = line.trimmingCharacters(in: .whitespacesAndNewlines).split(separator: " ")
                    if parts.first == "quit" { NSApp.terminate(nil) }
                    if let mode = parts.first { state.mode = String(mode) }
                    state.target = parts.count > 1 ? (Double(parts[1]) ?? 0) : 0
                }
                next()
            }
        }
        next()
    }
    listener.start(queue: .main)
    keep.append(listener)
}

var keep: [AnyObject] = []
var lastHeard = Date()

@MainActor
func preview(to dir: String) {
    for (mode, level) in [("listening", 0.15), ("thinking", 0.0), ("speaking", 0.7)] {
        let frozen = HaloState()
        frozen.mode = mode
        frozen.level = level
        let renderer = ImageRenderer(content: Orb(halo: frozen, frozenTime: 1.7).background(Color(white: 0.16)))
        renderer.scale = 2
        if let image = renderer.nsImage, let tiff = image.tiffRepresentation,
           let png = NSBitmapImageRep(data: tiff)?.representation(using: .png, properties: [:]) {
            try? png.write(to: URL(fileURLWithPath: "\(dir)/halo-\(mode).png"))
        }
    }
}

let args = CommandLine.arguments
if args.count > 2, args[1] == "--preview" {
    MainActor.assumeIsolated { preview(to: args[2]) }
    exit(0)
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)  // no Dock icon, never takes focus from Logic
let size = CGSize(width: 300, height: 300)
let panel = NSPanel(contentRect: CGRect(origin: .zero, size: size), styleMask: [.borderless, .nonactivatingPanel],
                    backing: .buffered, defer: false)
panel.isOpaque = false
panel.backgroundColor = .clear
panel.hasShadow = false
panel.level = .floating
panel.ignoresMouseEvents = true
panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
panel.contentView = NSHostingView(rootView: Orb(halo: state))
panel.orderFrontRegardless()

func place() {
    guard let screen = NSScreen.screens.first else { return }
    let target = logicFrame() ?? CGRect(x: screen.frame.midX - 1, y: screen.frame.height / 2 - 1, width: 2, height: 2)
    // the window list is top-left origin; AppKit is bottom-left on the primary screen
    let x = target.midX - size.width / 2
    let y = screen.frame.height - target.midY - size.height / 2
    panel.setFrameOrigin(CGPoint(x: x, y: y))
}
place()
// The booth sends 30 times a second; four seconds of silence means it has gone, so the halo goes too.
let timer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { _ in
    place()
    if Date().timeIntervalSince(lastHeard) > 4 { NSApp.terminate(nil) }
}
keep.append(timer)
listen()
app.run()
