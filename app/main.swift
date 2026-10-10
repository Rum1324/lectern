// Entry point for Lectern.app (see LecternApp.swift, PhoneLink.swift).
import Cocoa

let app = NSApplication.shared
let delegate = LecternApp()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
