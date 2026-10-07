# Lectern

Phone-as-trackpad and presentation remote for macOS. No app install on the phone, no pip install on the Mac.

## Start (Mac)

**Menu bar app (easiest).** Download `Lectern.app.zip` from the latest release, unzip, move
`Lectern.app` to Applications and open it. It is not notarized, so the first time macOS will say
it "cannot verify" the app: right-click → Open once, or run `xattr -d com.apple.quarantine
/Applications/Lectern.app`. The app sits in the menu bar, starts the server on launch with the
tunnel on (turn it off in the menu for a normal home network), shows the address it is serving,
opens the pairing QR, and stops everything when you quit. It needs the Xcode Command Line Tools
(`xcode-select --install`) for Python and the laser overlay; nothing else.

Or build it yourself with `./build-app.sh` (output in `dist/`).

**Terminal.**

```
cd lectern
python3 lectern.py            # direct Wi-Fi
python3 lectern.py --tunnel   # through Cloudflare, for networks that isolate clients
```

(or double-click `start.command`; if Finder blocks it, right-click → Open once)

1. A browser tab opens with a QR code. Scan it with the iPhone camera.
2. First run only: macOS needs **Accessibility** for the app that runs Lectern (Terminal, iTerm, …). The settings pane opens automatically; turn it on, then restart Lectern. Without it, macOS silently drops every click and key.
3. If macOS asks whether python3 may accept incoming connections, allow it.
4. On the phone: Share → **Add to Home Screen**. The pairing key is in that link and is saved on the Mac in `~/.config/lectern/token`, so you pair once.

## Install as an app (Android Chrome)

Over a fixed HTTPS address (see the tunnel setup under Limits), Chrome offers to install the page: open the QR link once, then menu ⋮ → **Install app** (or **Add to Home screen**). The pairing key is kept on the phone, so the installed app opens straight to the trackpad. Over plain LAN http, "Add to Home screen" still works but is a bookmark, not an install.

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
  - Tunnel (works on any network, adds internet round-trip delay): `python3 lectern.py --tunnel`. It uses `cloudflared` from Homebrew if present, otherwise downloads it once into `~/.config/lectern/`. Without setup the QR carries an `https://….trycloudflare.com` address that changes every run. With a domain on Cloudflare, run once `cloudflared tunnel login` and `python3 lectern.py --tunnel-setup lectern.yourdomain.com`; the address is then fixed and the phone can install the page as an app.
  - Phone hotspot: join the Mac to your phone's hotspot; the default QR then works.
- Bluetooth is not possible from a web page.
- **Laser** is drawn by `laser.swift`, compiled once with `swiftc` (ships with Xcode Command Line Tools). Without `swiftc`, the laser moves the cursor instead.
- **Silence** runs a Shortcut named `Lectern Focus`, because macOS has no command-line switch for Do Not Disturb. Create it in Shortcuts: *Set Focus → Do Not Disturb → Toggle*.
- Wake Lock needs HTTPS; the page keeps the phone awake with a 1.5 kB looping muted video instead.
- Anyone on the network with the key URL can control the Mac. Delete `~/.config/lectern/token` to rotate the key.

## Running it yourself

Everything runs on your own Mac; nothing is hosted. The tunnel modes use Cloudflare:

- **Quick tunnel** (no account): `--tunnel` with no setup gives a random `trycloudflare.com`
  address that changes every run.
- **Named tunnel** (fixed address, lets the phone install the page as an app): you need a
  Cloudflare account with a domain on it. Run `cloudflared tunnel login` once, then
  `python3 lectern.py --tunnel-setup lectern.yourdomain.com`. That creates a tunnel named
  `lectern` in your account and the DNS record; `--tunnel` uses it from then on.

## Options

`--tunnel` (public HTTPS address via Cloudflare) · `--tunnel-setup <hostname>` (one-time, fixed address) · `--port 8765` · `--dry-run` (log instead of acting) · `--no-browser` · `--token <key>`
