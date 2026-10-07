// Lectern laser dot. Reads lines from stdin:
//   show <x> <y>   (global CoreGraphics coordinates, origin at top-left of the main display)
//   hide
//   quit
// Draws a click-through red dot above every window, including full-screen slideshows.
import Cocoa

final class Dot: NSView {
    override func draw(_ dirtyRect: NSRect) {
        let glow = NSGradient(colors: [NSColor(red: 1, green: 0.15, blue: 0.1, alpha: 0.55),
                                       NSColor(red: 1, green: 0.15, blue: 0.1, alpha: 0)])
        glow?.draw(in: NSBezierPath(ovalIn: bounds), relativeCenterPosition: .zero)
        NSColor(red: 1, green: 0.2, blue: 0.15, alpha: 1).setFill()
        NSBezierPath(ovalIn: bounds.insetBy(dx: bounds.width * 0.32,
                                            dy: bounds.height * 0.32)).fill()
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)

let size: CGFloat = 44
let win = NSWindow(contentRect: NSRect(x: 0, y: 0, width: size, height: size),
                   styleMask: .borderless, backing: .buffered, defer: false)
win.isOpaque = false
win.backgroundColor = .clear
win.hasShadow = false
win.ignoresMouseEvents = true
win.level = .screenSaver
win.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
win.contentView = Dot(frame: NSRect(x: 0, y: 0, width: size, height: size))

func handle(_ line: String) {
    let parts = line.split(separator: " ")
    guard let cmd = parts.first else { return }
    switch cmd {
    case "show":
        guard parts.count == 3, let x = Double(parts[1]), let y = Double(parts[2]) else { return }
        // CoreGraphics y grows downward from the main display's top; Cocoa y grows upward.
        let mainHeight = NSScreen.screens.first?.frame.height ?? 0
        win.setFrameOrigin(NSPoint(x: CGFloat(x) - size / 2,
                                   y: mainHeight - CGFloat(y) - size / 2))
        if !win.isVisible { win.orderFrontRegardless() }
    case "hide":
        win.orderOut(nil)
    case "quit":
        exit(0)
    default:
        break
    }
}

DispatchQueue.global().async {
    while let line = readLine() {
        DispatchQueue.main.async { handle(line) }
    }
    exit(0)  // parent closed stdin
}

app.run()
