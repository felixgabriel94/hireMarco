// Marco on the Mac: a menu-bar app that starts his booth when Logic opens and stops it when Logic quits.
//
// No typing: log in, open Logic, say "Hey Marco". The menu shows whether he is listening and can pause him,
// text the live view link, or quit. The booth runs in a Terminal window this app opens, so macOS asks once
// for the microphone, Accessibility and Screen Recording through Terminal, which already holds them (see start()).
// This file is kept small on purpose; the halo and the booth, which change often, live in their own programs.
//
// It reads the repository and uv paths from ~/.local/state/hiremarco/app.json, written by `marco app build`.
import AppKit
import ApplicationServices
import CoreGraphics
import Network

let logicID = "com.apple.logic10"
let stateDir = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/state/hiremarco")

struct Paths: Decodable { let repo: String; let uv: String }

func loadPaths() -> Paths? {
    guard let data = try? Data(contentsOf: stateDir.appendingPathComponent("app.json")) else { return nil }
    return try? JSONDecoder().decode(Paths.self, from: data)
}

final class Marco: NSObject, NSApplicationDelegate {
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    let status = NSMenuItem(title: "Waiting for Logic", action: nil, keyEquivalent: "")
    let pauseItem = NSMenuItem(title: "Pause Marco", action: #selector(togglePause), keyEquivalent: "")
    let boothItem = NSMenuItem(title: "Listen in the booth (vocal mic)", action: #selector(atBooth), keyEquivalent: "")
    let deskItem = NSMenuItem(title: "Listen at the desk (MacBook mic)", action: #selector(atDesk), keyEquivalent: "")
    let booth = NWConnection(host: "127.0.0.1", port: 8790, using: .udp)
    var paused = false
    let paths = loadPaths()

    func applicationDidFinishLaunching(_ note: Notification) {
        // the tie, in its own blue, so the menu bar stays on brand (menubar.png and @2x in Resources)
        if let tie = Bundle.main.image(forResource: "menubar") {
            tie.size = NSSize(width: 18, height: 18)
            tie.isTemplate = false
            item.button?.image = tie
        } else {
            item.button?.image = NSImage(systemSymbolName: "waveform.circle", accessibilityDescription: "hireMarco")
        }
        let menu = NSMenu()
        status.isEnabled = false
        menu.addItem(status)
        menu.addItem(.separator())
        menu.addItem(boothItem)
        menu.addItem(deskItem)
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Text me the live view", action: #selector(liveView), keyEquivalent: ""))
        menu.addItem(pauseItem)
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Quit Marco", action: #selector(quit), keyEquivalent: ""))
        for entry in menu.items { entry.target = self }
        boothItem.state = .on
        item.menu = menu
        booth.start(queue: .main)

        let center = NSWorkspace.shared.notificationCenter
        center.addObserver(self, selector: #selector(launched(_:)), name: NSWorkspace.didLaunchApplicationNotification,
                           object: nil)
        center.addObserver(self, selector: #selector(terminated(_:)),
                           name: NSWorkspace.didTerminateApplicationNotification, object: nil)
        if paths == nil { show("Run `marco app build` once") }
        askForAccess()
        if NSWorkspace.shared.runningApplications.contains(where: { $0.bundleIdentifier == logicID }) { start() }
    }

    func show(_ text: String) { status.title = text }

    // macOS adds an app built on this Mac to the Accessibility and Screen Recording lists only when the app asks
    // for itself; picking it with + did nothing (live 2026-10-29). Each call shows the system's own prompt once.
    func askForAccess() {
        let prompt = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
        if !AXIsProcessTrustedWithOptions([prompt: true] as CFDictionary) { show("Allow hireMarco in Accessibility") }
        if !CGPreflightScreenCaptureAccess() { _ = CGRequestScreenCaptureAccess() }
    }

    @objc func launched(_ note: Notification) {
        let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication
        if app?.bundleIdentifier == logicID { start() }
    }

    @objc func terminated(_ note: Notification) {
        let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication
        if app?.bundleIdentifier == logicID { stop("Waiting for Logic") }
    }

    // The booth runs in Terminal, started from a .command file: macOS will not list an app built on this Mac in
    // Accessibility or Screen Recording (live 2026-10-29, even when it asked), and Terminal already holds both.
    // Opening a .command file needs no extra permission; the window shows his log as he works.
    var listening = false

    func start() {
        guard !listening, !paused, let paths else { return }
        let log = stateDir.appendingPathComponent("booth.log").path
        let script = stateDir.appendingPathComponent("booth.command")
        let body = """
        #!/bin/zsh
        printf '\\e]0;hireMarco\\a'
        echo "hireMarco: listening while Logic is open. This window closes when he stops."
        cd '\(paths.repo)' || exit 1
        export HIREMARCO_FROM_APP=1 PYTHONUNBUFFERED=1
        '\(paths.uv)' run marco booth 2>&1 | tee -a '\(log)'
        exit
        """
        do {
            try body.write(to: script, atomically: true, encoding: .utf8)
            try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: script.path)
        } catch {
            show("Could not start: \(error.localizedDescription)")
            return
        }
        let terminal = URL(fileURLWithPath: "/System/Applications/Utilities/Terminal.app")
        NSWorkspace.shared.open([script], withApplicationAt: terminal, configuration: NSWorkspace.OpenConfiguration())
        listening = true
        boothItem.state = .on
        deskItem.state = .off
        show("Listening in Logic")
    }

    func stop(_ label: String) {
        show(label)
        guard listening else { return }
        // the booth's own Ctrl+C, asked for over the shortcut port: mic, halo and live view close cleanly
        booth.send(content: "stop".data(using: .utf8), completion: .contentProcessed { _ in })
        listening = false
    }

    // Where you are, picked by you: mixing can happen at the mic, so the mode does not decide it. Each booth start
    // begins in the booth.
    @objc func atBooth() { place("booth") }
    @objc func atDesk() { place("desk") }

    func place(_ spot: String) {
        booth.send(content: "place \(spot)".data(using: .utf8), completion: .contentProcessed { _ in })
        boothItem.state = spot == "booth" ? .on : .off
        deskItem.state = spot == "desk" ? .on : .off
    }

    @objc func liveView() {
        booth.send(content: "live".data(using: .utf8), completion: .contentProcessed { _ in })
    }

    @objc func togglePause() {
        paused.toggle()
        pauseItem.title = paused ? "Resume Marco" : "Pause Marco"
        if paused { stop("Paused") } else if NSWorkspace.shared.runningApplications.contains(where: {
            $0.bundleIdentifier == logicID }) { start() } else { show("Waiting for Logic") }
    }

    // Quit from anywhere (the menu, Activity Monitor, `quit app`): the booth goes with it, never left listening.
    func applicationWillTerminate(_ note: Notification) {
        if listening {
            booth.send(content: "stop".data(using: .utf8), completion: .contentProcessed { _ in })
            usleep(300_000)
        }
    }

    @objc func quit() {
        stop("Quitting")
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) { NSApp.terminate(nil) }
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let marco = Marco()
app.delegate = marco
app.run()
