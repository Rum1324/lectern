// Lectern menu bar app: a thin launcher for lectern.py.
// Starts/stops the Python server, shows its public address, toggles the Cloudflare tunnel
// (default on, for networks that isolate clients), opens the pairing QR page.
// Built by build-app.sh with swiftc; no Xcode project, no dependencies.
import Cocoa

final class LecternApp: NSObject, NSApplicationDelegate {
    private var item: NSStatusItem!
    private let menu = NSMenu()
    private let statusLine = NSMenuItem(title: "Stopped", action: nil, keyEquivalent: "")
    private let startStop = NSMenuItem(title: "Start", action: #selector(toggleServer), keyEquivalent: "")
    private let qrItem = NSMenuItem(title: "Show pairing QR…", action: #selector(showQR), keyEquivalent: "")
    private let axItem = NSMenuItem(title: "Grant Accessibility…", action: #selector(openAccessibility), keyEquivalent: "")
    private let tunnelItem = NSMenuItem(title: "Use tunnel (campus Wi-Fi)", action: #selector(toggleTunnel), keyEquivalent: "")
    private let logItem = NSMenuItem(title: "Open log", action: #selector(openLog), keyEquivalent: "")
    private var proc: Process?
    private var restartAfterStop = false
    private var pending = ""
    private let port = 8765
    private let logPath = NSHomeDirectory() + "/.config/lectern/app.log"

    private var useTunnel: Bool {
        get { UserDefaults.standard.object(forKey: "tunnel") as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: "tunnel") }
    }

    func applicationDidFinishLaunching(_ note: Notification) {
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let img = NSImage(systemSymbolName: "rectangle.and.hand.point.up.left",
                             accessibilityDescription: "Lectern") {
            img.isTemplate = true
            item.button?.image = img
        } else {
            item.button?.title = "L"
        }
        let quit = NSMenuItem(title: "Quit Lectern", action: #selector(quitApp), keyEquivalent: "q")
        statusLine.isEnabled = false
        for m in [statusLine, .separator(), startStop, qrItem, axItem, .separator(),
                  tunnelItem, logItem, .separator(), quit] {
            m.target = self
            menu.addItem(m)
        }
        axItem.isHidden = true
        item.menu = menu
        try? FileManager.default.createDirectory(atPath: (logPath as NSString).deletingLastPathComponent,
                                                 withIntermediateDirectories: true)
        render()
        start()
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if let p = proc, p.isRunning {
            p.terminate()            // SIGTERM: lectern.py stops cloudflared and the laser helper
            let deadline = Date().addingTimeInterval(3)
            while p.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.05) }
            if p.isRunning { kill(p.processIdentifier, SIGKILL) }
        }
        return .terminateNow
    }

    // MARK: server process

    private func start() {
        guard proc == nil, let res = Bundle.main.resourcePath else { return }
        FileManager.default.createFile(atPath: logPath, contents: nil)
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        var args = ["-u", res + "/lectern.py", "--no-browser", "--port", String(port)]
        if useTunnel { args.append("--tunnel") }
        p.arguments = args
        p.currentDirectoryURL = URL(fileURLWithPath: res)
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        let log = FileHandle(forWritingAtPath: logPath)
        pipe.fileHandleForReading.readabilityHandler = { [weak self] h in
            let d = h.availableData
            if d.isEmpty { return }
            log?.write(d)
            DispatchQueue.main.async { self?.consume(String(decoding: d, as: UTF8.self)) }
        }
        p.terminationHandler = { [weak self] _ in
            pipe.fileHandleForReading.readabilityHandler = nil
            try? log?.close()
            DispatchQueue.main.async {
                guard let s = self else { return }
                s.proc = nil
                s.statusLine.title = "Stopped"
                s.axItem.isHidden = true
                s.render()
                if s.restartAfterStop { s.restartAfterStop = false; s.start() }
            }
        }
        do {
            try p.run()
            proc = p
            statusLine.title = useTunnel ? "Starting tunnel…" : "Starting…"
        } catch {
            statusLine.title = "Could not start python3 (install Xcode Command Line Tools)"
        }
        render()
    }

    private func stop() {
        proc?.terminate()
    }

    /// Reads lectern.py's output line by line and turns the interesting lines into status.
    private func consume(_ text: String) {
        pending += text
        while let nl = pending.firstIndex(of: "\n") {
            let line = String(pending[..<nl]).trimmingCharacters(in: .whitespaces)
            pending = String(pending[pending.index(after: nl)...])
            if line.hasPrefix("open on your phone: "), statusLine.title.hasPrefix("Start") {
                let url = String(line.dropFirst("open on your phone: ".count))
                let host = URL(string: url)?.host ?? url
                statusLine.title = "Running · " + host
            } else if line.hasPrefix("tunnel: downloading cloudflared") {
                statusLine.title = "Downloading cloudflared (first run)…"
            } else if line.hasPrefix("! macOS has not granted Accessibility") {
                statusLine.title = "Accessibility needed, then Stop and Start"
                axItem.isHidden = false
            } else if line.hasPrefix("! tunnel: no public URL") {
                statusLine.title = "Tunnel failed (see log); LAN only"
            }
        }
    }

    private func render() {
        let running = proc != nil
        startStop.title = running ? "Stop" : "Start"
        qrItem.isEnabled = running
        tunnelItem.state = useTunnel ? .on : .off
    }

    // MARK: actions

    @objc private func toggleServer() {
        if proc == nil { start() } else { stop() }
    }

    @objc private func toggleTunnel() {
        useTunnel.toggle()
        render()
        if proc != nil { restartAfterStop = true; stop() }
    }

    @objc private func showQR() {
        NSWorkspace.shared.open(URL(string: "http://127.0.0.1:\(port)/pair")!)
    }

    @objc private func openAccessibility() {
        NSWorkspace.shared.open(URL(string:
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")!)
    }

    @objc private func openLog() {
        NSWorkspace.shared.open(URL(fileURLWithPath: logPath))
    }

    @objc private func quitApp() {
        NSApp.terminate(nil)
    }
}

let app = NSApplication.shared
let delegate = LecternApp()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
