# Lectern

Phone-as-trackpad and presentation remote for macOS. No app install on the phone, no pip install on the Mac.

## Start (Mac)

```
cd lectern
python3 lectern.py
```

(or double-click `start.command`; if Finder blocks it, right-click → Open once)

1. A browser tab opens with a QR code. Scan it with the iPhone camera.
2. First run only: macOS needs **Accessibility** for the app that runs Lectern (Terminal, iTerm, …). The settings pane opens automatically; turn it on, then restart Lectern. Without it, macOS silently drops every click and key.
3. If macOS asks whether python3 may accept incoming connections, allow it.
4. On the phone: Share → **Add to Home Screen**. The pairing key is in that link and is saved on the Mac in `~/.config/lectern/token`, so you pair once.

## Gestures

| Trackpad tab | Mac action |
|---|---|
| 1 finger drag | move pointer (speeds up with finger speed) |
| tap / tap tap | click / double-click |
| 2-finger tap | right click |
| 2-finger drag | scroll, with momentum |
| double-tap, hold, drag | drag |
| hold **Left** + move with another finger | drag |

Present tab: Back / Next (arrow keys), laser (hold and drag), Blank (`B`, works in Keynote, PowerPoint, Google Slides), volume − / mute / +, talk timer (tap start/pause, hold to reset).

## Limits

- **Direct connection by default.** Networks with client isolation (many campus and hotel networks) block phone → Mac traffic. Two ways around it:
  - Tunnel (works on any network, adds internet round-trip delay): `python3 lectern.py --tunnel`. It uses `cloudflared` from Homebrew if present, otherwise downloads it once into `~/.config/lectern/`. The QR then carries an `https://….trycloudflare.com` address that changes every run, so the Home Screen shortcut only lasts one session.
  - Phone hotspot: join the Mac to your phone's hotspot; the default QR then works.
- Bluetooth is not possible from a web page.
- **Laser** is drawn by `laser.swift`, compiled once with `swiftc` (ships with Xcode Command Line Tools). Without `swiftc`, the laser moves the cursor instead.
- **Silence** runs a Shortcut named `Lectern Focus`, because macOS has no command-line switch for Do Not Disturb. Create it in Shortcuts: *Set Focus → Do Not Disturb → Toggle*.
- Wake Lock needs HTTPS; the page keeps the phone awake with a 1.5 kB looping muted video instead.
- Anyone on the network with the key URL can control the Mac. Delete `~/.config/lectern/token` to rotate the key.

## Options

`--tunnel` (public HTTPS address via Cloudflare) · `--port 8765` · `--dry-run` (log instead of acting) · `--no-browser` · `--token <key>`
