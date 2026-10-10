# Lectern

Phone-as-trackpad and presentation remote for macOS. Two ways in:

- **Web page** (any phone, iPhone included): no app install on the phone, no pip install on the Mac. Needs the phone and Mac to reach each other over Wi-Fi, or the Cloudflare tunnel.
- **Android app over Bluetooth** (Android 9+): the phone becomes a Bluetooth mouse and keyboard. No Wi-Fi, no tunnel, nothing required on the Mac. See [Android app](#android-app-bluetooth).

## Start (Mac)

**Menu bar app (easiest).** Download `Lectern.app.zip` from the latest release, unzip, move
`Lectern.app` to Applications and open it. It is not notarized, so the first time macOS will say
it "cannot verify" the app: right-click → Open once, or run `xattr -d com.apple.quarantine
/Applications/Lectern.app`. The app sits in the menu bar, starts the server on launch with the
tunnel on (turn it off in the menu for a normal home network), shows the address it is serving,
opens the pairing QR, and stops everything when you quit. It needs the Xcode Command Line Tools
(`xcode-select --install`) for Python and the laser overlay; nothing else.

Or build it yourself with `./build-app.sh` (output in `dist/`). If you rebuild often, run
`./make-signing-cert.sh` once first: it creates a free self-signed signing certificate so macOS
keeps the Accessibility grant across rebuilds.

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

## Android app (Bluetooth)

Same screens as the web page, but connected over Bluetooth, so it works on networks that block
phone-to-Mac traffic and with no network at all.

1. On the phone, download `Lectern-<version>.apk` from the latest release and open it. Android asks
   once to allow installs from your browser; allow it. (The app is not on the Play Store.)
2. Open Lectern, allow **Nearby devices**, tap **Make discoverable**.
3. On the Mac: System Settings → Bluetooth → **Connect** next to the phone, confirm the code on both.

From then on, opening Lectern reconnects by itself. A notification stays up while it is active, so
Android doesn't kill it in the background; tap **Stop** there (or swipe Lectern away) to disconnect.

**Optional, on the Mac: the menu bar app as helper.** With `Lectern.app` running, the phone shows
"Mac helper" and scrolling is smooth pixel scrolling, the laser draws a dot, Silence works. Without
it, the phone still works as a plain mouse: scrolling falls back to mouse-wheel steps (macOS makes
those choppy) and the laser area moves the pointer. The helper needs **Input Monitoring** for
Lectern.app (System Settings → Privacy & Security → Input Monitoring; use **+** if it isn't
listed) in addition to Accessibility. The helper and the phone find each other on their own.

If the Mac shows the phone connected but nothing moves: in Lectern, Settings → Bluetooth →
Devices, tap your Mac (reconnects). If that fails, disconnect the phone in the Mac's Bluetooth
settings and pick the Mac again. After updating to a version whose release notes say "re-pair":
Forget the phone on the Mac, unpair the Mac on the phone, and pair again (the Mac caches the
phone's device description).

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
- Bluetooth is not possible from a web page; use the [Android app](#android-app-bluetooth). iPhones can't act as Bluetooth mice for apps, so iPhone stays on the web page.
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
