// Bluetooth helper for the Lectern Android app (android/).
//
// Over Bluetooth the phone is a plain HID mouse/keyboard, which macOS scrolls in accelerated
// wheel notches (choppy, eased per notch by apps) and which cannot draw a laser dot. The phone's
// HID descriptor therefore also has a vendor collection (usage page 0xFF00):
//   input report 4, 8 bytes: [type, a lo, a hi, b lo, b hi, 0, 0, 0]
//     type 1 scroll  a = dx, b = dy  (quarter pixels; page sign convention, as lectern.py posts)
//     type 2 laser   a = dx, b = dy  (quarter points)
//     type 3 laser hide
//     type 4 focus   (run the "Lectern Focus" Shortcut, as lectern.py does)
//   output report 5, 2 bytes: [1, 0], a heartbeat this helper sends every second.
// The phone uses the vendor reports only while heartbeats arrive, so when this app is not
// running it falls back to wheel notches and moves the pointer for the laser.
//
// Reading the phone's reports needs Input Monitoring (the device includes a keyboard);
// posting scroll events needs Accessibility, which Lectern.app already has.
import Cocoa
import IOKit.hid

final class PhoneLink {
    /// Number of Lectern phones currently connected over Bluetooth; nil while Input Monitoring is missing.
    private(set) var phones: Int? = 0
    var onChange: (() -> Void)?

    private let manager = IOHIDManagerCreate(kCFAllocatorDefault, IOOptionBits(kIOHIDOptionsTypeNone))
    private var devices: [IOHIDDevice] = []
    private var buffers: [UnsafeMutablePointer<UInt8>] = []
    private var opened = false
    private var heartbeat: Timer?
    private let io = DispatchQueue(label: "lectern.phonelink")
    private let scroll = Pacer(integer: true) { dx, dy in PhoneLink.postScroll(dx, dy) }
    private let laser = LaserDot()
    private lazy var laserPace = Pacer(integer: false) { [weak self] dx, dy in self?.laser.move(dx, dy) }

    func start() {
        IOHIDManagerSetDeviceMatching(manager, [
            kIOHIDDeviceUsagePageKey: 0xFF00, kIOHIDDeviceUsageKey: 0x01,
        ] as CFDictionary)
        let ctx = Unmanaged.passUnretained(self).toOpaque()
        IOHIDManagerRegisterDeviceMatchingCallback(manager, { ctx, _, _, dev in
            Unmanaged<PhoneLink>.fromOpaque(ctx!).takeUnretainedValue().added(dev)
        }, ctx)
        IOHIDManagerRegisterDeviceRemovalCallback(manager, { ctx, _, _, dev in
            Unmanaged<PhoneLink>.fromOpaque(ctx!).takeUnretainedValue().removed(dev)
        }, ctx)
        IOHIDManagerScheduleWithRunLoop(manager, CFRunLoopGetMain(), CFRunLoopMode.defaultMode.rawValue)
        // Ask once at launch: this is what puts Lectern into the Input Monitoring list (with the
        // system prompt). Without it the app never shows up there and can only be added with "+".
        if IOHIDCheckAccess(kIOHIDRequestTypeListenEvent) == kIOHIDAccessTypeUnknown {
            _ = IOHIDRequestAccess(kIOHIDRequestTypeListenEvent)
        }
        open()
        heartbeat = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            if !self.opened { self.open() }  // Input Monitoring may have been granted since
            self.beat()
        }
    }

    /// Asks macOS for Input Monitoring (shows the system prompt the first time).
    func requestAccess() {
        _ = IOHIDRequestAccess(kIOHIDRequestTypeListenEvent)
        NSWorkspace.shared.open(URL(string:
            "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent")!)
    }

    private func open() {
        guard IOHIDCheckAccess(kIOHIDRequestTypeListenEvent) == kIOHIDAccessTypeGranted else {
            if phones != nil { phones = nil; onChange?() }
            return
        }
        opened = IOHIDManagerOpen(manager, IOOptionBits(kIOHIDOptionsTypeNone)) == kIOReturnSuccess
        if opened && phones == nil { phones = devices.count; onChange?() }
    }

    private func added(_ dev: IOHIDDevice) {
        guard !devices.contains(where: { $0 === dev }) else { return }
        devices.append(dev)
        let buf = UnsafeMutablePointer<UInt8>.allocate(capacity: 64)
        buffers.append(buf)
        let ctx = Unmanaged.passUnretained(self).toOpaque()
        IOHIDDeviceRegisterInputReportCallback(dev, buf, 64, { ctx, _, _, _, id, report, len in
            Unmanaged<PhoneLink>.fromOpaque(ctx!).takeUnretainedValue().report(id, report, len)
        }, ctx)
        phones = devices.count
        onChange?()
        beat()
    }

    private func removed(_ dev: IOHIDDevice) {
        devices.removeAll { $0 === dev }
        if devices.isEmpty { laserPace.drop(); laser.hide() }
        phones = opened ? devices.count : nil
        onChange?()
    }

    private func beat() {
        let devs = devices
        io.async {
            var hb: [UInt8] = [5, 1, 0] // macOS wants the report ID as the first byte
            for d in devs { _ = IOHIDDeviceSetReport(d, kIOHIDReportTypeOutput, 5, &hb, hb.count) }
        }
    }

    private func report(_ id: UInt32, _ p: UnsafeMutablePointer<UInt8>, _ len: CFIndex) {
        // The buffer may or may not start with the report ID byte.
        var o = 0
        if id == 4 && len == 9 && p[0] == 4 { o = 1 } else if !(id == 4 && len == 8) { return }
        func i16(_ at: Int) -> Double { Double(Int16(bitPattern: UInt16(p[o + at]) | UInt16(p[o + at + 1]) << 8)) / 4 }
        switch p[o] {
        case 1: scroll.add(i16(1), i16(3))
        case 2: laserPace.add(i16(1), i16(3))
        case 3: laserPace.drop(); laser.hide()
        case 4: PhoneLink.runFocusShortcut()
        default: break
        }
    }

    private static func postScroll(_ dx: Double, _ dy: Double) {
        // Same event lectern.py posts: pixel units, wheel1 vertical, wheel2 horizontal.
        CGEvent(scrollWheelEvent2Source: nil, units: .pixel, wheelCount: 2,
                wheel1: Int32(dy), wheel2: Int32(dx), wheel3: 0)?.post(tap: .cghidEventTap)
    }

    private static func runFocusShortcut() {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/shortcuts")
        p.arguments = ["run", "Lectern Focus"]
        try? p.run()
    }
}

/// Port of lectern.py's Pacer: releases half the backlog every 1/120 s, totals exact.
final class Pacer {
    private var x = 0.0, y = 0.0
    private var timer: Timer?
    private let integer: Bool
    private let emit: (Double, Double) -> Void

    init(integer: Bool, emit: @escaping (Double, Double) -> Void) {
        self.integer = integer
        self.emit = emit
    }

    func add(_ dx: Double, _ dy: Double) {
        x += dx; y += dy
        if timer == nil {
            let t = Timer(timeInterval: 1.0 / 120, repeats: true) { [weak self] _ in self?.step() }
            RunLoop.main.add(t, forMode: .common)
            timer = t
            step()
        }
    }

    func drop() { x = 0; y = 0 }

    private func step() {
        if x == 0 && y == 0 { timer?.invalidate(); timer = nil; return }
        var dx = x * 0.5, dy = y * 0.5
        if integer {
            dx = dx.rounded(.towardZero); dy = dy.rounded(.towardZero)
            if (dx == 0 && dy == 0) || max(abs(x), abs(y)) < 2 {
                // Whole pixels only: emit what is whole, keep the fraction for later input.
                dx = x.rounded(.towardZero); dy = y.rounded(.towardZero)
                if dx == 0 && dy == 0 { x = 0; y = 0; return }
            }
        } else if max(abs(x), abs(y)) < 1 {
            dx = x; dy = y
        }
        x -= dx; y -= dy
        if abs(x) < 1e-9 { x = 0 }
        if abs(y) < 1e-9 { y = 0 }
        emit(dx, dy)
    }
}

/// The laser dot from laser.swift, in-process. Starts at the cursor, clamped to the displays.
final class LaserDot {
    private let size: CGFloat = 44
    private lazy var win: NSWindow = {
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: size, height: size),
                         styleMask: .borderless, backing: .buffered, defer: false)
        w.isOpaque = false
        w.backgroundColor = .clear
        w.hasShadow = false
        w.ignoresMouseEvents = true
        w.level = .screenSaver
        w.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        w.contentView = DotView(frame: NSRect(x: 0, y: 0, width: size, height: size))
        return w
    }()
    private var pos: CGPoint?

    func move(_ dx: Double, _ dy: Double) {
        var p = pos ?? (CGEvent(source: nil)?.location ?? .zero)
        let b = LaserDot.displayBounds()
        p.x = min(max(p.x + CGFloat(dx), b.minX), b.maxX - 1)
        p.y = min(max(p.y + CGFloat(dy), b.minY), b.maxY - 1)
        pos = p
        // CoreGraphics y grows downward from the main display's top; Cocoa y grows upward.
        let mainHeight = NSScreen.screens.first?.frame.height ?? 0
        win.setFrameOrigin(NSPoint(x: p.x - size / 2, y: mainHeight - p.y - size / 2))
        if !win.isVisible { win.orderFrontRegardless() }
    }

    func hide() {
        if pos != nil { win.orderOut(nil) }
        pos = nil
    }

    private static func displayBounds() -> CGRect {
        var ids = [CGDirectDisplayID](repeating: 0, count: 16)
        var n: UInt32 = 0
        guard CGGetActiveDisplayList(16, &ids, &n) == .success, n > 0 else { return CGDisplayBounds(CGMainDisplayID()) }
        return ids[0..<Int(n)].map { CGDisplayBounds($0) }.reduce(CGRect.null) { $0.union($1) }
    }
}

final class DotView: NSView {
    override func draw(_ dirtyRect: NSRect) {
        let glow = NSGradient(colors: [NSColor(red: 1, green: 0.15, blue: 0.1, alpha: 0.55),
                                       NSColor(red: 1, green: 0.15, blue: 0.1, alpha: 0)])
        glow?.draw(in: NSBezierPath(ovalIn: bounds), relativeCenterPosition: .zero)
        NSColor(red: 1, green: 0.2, blue: 0.15, alpha: 1).setFill()
        NSBezierPath(ovalIn: bounds.insetBy(dx: bounds.width * 0.32, dy: bounds.height * 0.32)).fill()
    }
}
