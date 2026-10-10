// Lectern menu bar app: a thin launcher for lectern.py.
// Starts/stops the Python server, shows its public address, toggles the Cloudflare tunnel
// (default on, for networks that isolate clients), opens the pairing QR page.
// Also hosts PhoneLink, the helper for the Android app's Bluetooth mode (smooth scroll, laser).
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
    private let phoneItem = NSMenuItem(title: "", action: #selector(phoneClicked), keyEquivalent: "")
    private let fixedItem = NSMenuItem(title: "Use my fixed address", action: #selector(toggleFixed), keyEquivalent: "")
    private let advancedItem = NSMenuItem(title: "Advanced", action: nil, keyEquivalent: "")
    private let phoneLink = PhoneLink()
    private var proc: Process?
    private var restartAfterStop = false
    private var pending = ""
    private let port = 8765
    private let logPath = NSHomeDirectory() + "/.config/lectern/app.log"

    private var useTunnel: Bool {
        get { UserDefaults.standard.object(forKey: "tunnel") as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: "tunnel") }
    }

    /// Named tunnel from `lectern.py --tunnel-setup` (fixed https address), if this Mac has one.
    private var fixedHost: String? {
        guard let text = try? String(contentsOfFile: NSHomeDirectory() + "/.config/lectern/tunnel.yml", encoding: .utf8),
              let r = text.range(of: #"hostname:\s*(\S+)"#, options: .regularExpression) else { return nil }
        return String(text[r]).components(separatedBy: CharacterSet.whitespaces).last
    }

    /// Off: a random quick-tunnel address even though a fixed one is set up (what new users get).
    private var useFixed: Bool {
        get { UserDefaults.standard.object(forKey: "fixedAddress") as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: "fixedAddress") }
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
                  phoneItem, .separator(), tunnelItem, advancedItem, logItem, .separator(), quit] {
            m.target = self
            menu.addItem(m)
        }
        axItem.isHidden = true
        let advanced = NSMenu()
        fixedItem.target = self
        advanced.addItem(fixedItem)
        advancedItem.submenu = advanced
        item.menu = menu
        try? FileManager.default.createDirectory(atPath: (logPath as NSString).deletingLastPathComponent,
                                                 withIntermediateDirectories: true)
        phoneLink.onChange = { [weak self] in self?.render() }
        phoneLink.start()
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
        if useTunnel && fixedHost != nil && !useFixed { args.append("--quick-tunnel") }
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
        let host = fixedHost
        advancedItem.isHidden = host == nil
        fixedItem.title = "Use my fixed address (\(host ?? ""))"
        fixedItem.state = useFixed ? .on : .off
        fixedItem.isEnabled = useTunnel
        switch phoneLink.phones {
        case nil: phoneItem.title = "Bluetooth phone: grant Input Monitoring…"
        case 0?: phoneItem.title = "Bluetooth phone: not connected"
        case let n?: phoneItem.title = n == 1 ? "Bluetooth phone: connected (smooth scroll, laser)"
                                              : "Bluetooth phones: \(n) connected"
        }
        phoneItem.isEnabled = phoneLink.phones == nil
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

    @objc private func toggleFixed() {
        useFixed.toggle()
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

    @objc private func phoneClicked() {
        phoneLink.requestAccess()
    }

    @objc private func openLog() {
        NSWorkspace.shared.open(URL(fileURLWithPath: logPath))
    }

    @objc private func quitApp() {
        NSApp.terminate(nil)
    }
}
