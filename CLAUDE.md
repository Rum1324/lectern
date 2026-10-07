# Lectern — handoff notes for Claude Code

Phone-as-trackpad and presentation remote for macOS. Functional equivalent of Mousely
(mouse.ly, seen in an Instagram reel). Copy the *features* only: the name, look, icon and
copy are original and must stay that way.

Owner: Sota. Phone: **Android** (Chrome). Laptop: Mac. Main venue: UC Berkeley, where campus
Wi-Fi likely blocks phone→laptop traffic (inferred, not verified).

## Status at handoff

| Part | Status |
|---|---|
| WebSocket protocol, pairing, HTTP serving | tested (`tests/test_protocol.py`, 10 tests, dry-run) |
| Phone gestures → events | tested (`tests/test_ui.py`, 9 tests, Chromium mobile viewport + CDP touch events) |
| **CoreGraphics ctypes calls** (`MacBackend`) | **untested** — written on Linux, never run on macOS |
| **`laser.swift`** overlay | **untested** — never compiled |
| osascript volume, `shortcuts run` focus toggle, Accessibility check | **untested** |
| Tunnel (cloudflared quick tunnel) | **untested** — manual; see backlog #2 |
| Real Android phone over Wi-Fi | **untested** |

**First job on the Mac:** run `python3 lectern.py`, pair the Android phone, and walk the
manual checklist below. Fix whatever breaks before adding features.

## Run and test

```
python3 lectern.py                 # real mode (macOS); opens pairing page with QR
python3 lectern.py --dry-run       # logs "[dry-run] ..." instead of posting events; any OS
python3 -m unittest discover -s tests -v   # 19 tests, ~15 s; UI tests skip without Playwright
pip install playwright && python3 -m playwright install chromium   # for tests/test_ui.py
```

## Files

```
lectern.py        server: HTTP + hand-rolled WebSocket (asyncio), Controller, backends
laser.swift       red-dot overlay; compiled by lectern.py with swiftc into ~/.config/lectern/
web/index.html    the whole phone app (HTML+CSS+JS, one file, no build step)
web/pair.html     QR pairing page, served only to a browser on the Mac itself
web/icon.png      home-screen icon (original)
start.command     double-click launcher
tests/            protocol + UI tests (see above)
```

## Hard constraints (keep these unless Sota says otherwise)

- **Zero dependencies on the Mac.** stdlib only, **Python 3.9 compatible** (the python3 from
  Xcode Command Line Tools). No `match`, no `X | Y` type unions at runtime.
  Check: `python3 -c "import ast;ast.parse(open('lectern.py').read(),feature_version=(3,9))"`
- **No build step for the phone app.** One HTML file; it must work on Android Chrome and iOS Safari.
- **Pairing key never leaves the Mac except inside the QR/URL.** `/pair` and `/pair.json`
  are served only when peer is loopback AND Host is localhost AND no forwarding headers
  (a tunnel also connects from 127.0.0.1). Don't weaken this; there is a test for it.

## Architecture

Phone page ⇄ WebSocket `/ws?k=<key>` ⇄ `Server.dispatch` → `Controller` → backend.
Backend is `MacBackend` (ctypes → CoreGraphics `CGEventPost`) or `DryRunBackend` (logs).

Client → server messages (JSON text frames):

| `t` | fields | effect |
|---|---|---|
| `m` | `dx, dy` (Mac points, accel already applied) | move pointer; dragged-event if a button is held |
| `click` | `b: left/right` | down+up; left clicks get clickState 2/3 when repeated within 0.45 s and 6 pt |
| `btn` | `b, down` | hold/release (drag). Always clickState 1, so a drag after a tap isn't a word-select |
| `s` | `dx, dy` (pixels, ints) | scroll; phone already applied natural-scroll sign |
| `key` | `k: left/right/b/esc/...` | key tap (codes in `KEY`) |
| `laser` | `dx, dy` or `on:false` | move/hide laser dot (falls back to moving cursor if no Swift helper) |
| `vol` | `a: up/down/mute/get` | osascript; replies `{t:vol, level, muted}` |
| `focus` | – | runs Shortcut "Lectern Focus"; replies `{t:note, text}` |
| `ping` | – | replies `pong`; phone sends every 5 s, server drops idle sockets after 30 s |

Server → client: `hello {host, trusted}`, `vol`, `note`, `pong`.

Details that are easy to break:
- Coordinates are CoreGraphics global (origin top-left of main display). `laser.swift`
  converts to Cocoa (origin bottom-left) using the main screen height.
- Natural scrolling: fingers move up → `dy < 0` → wheel1 negative → content scrolls down.
- Phone batches move/scroll/laser to one message per animation frame (`flush()`).
- Gestures use `targetTouches`, so holding the Left button while moving on the pad works.
- Disconnect releases any held button (`Controller.release_all`).
- Phone keep-awake: Wake Lock needs HTTPS, so over plain LAN HTTP a 1.5 kB muted looping
  video (base64 in index.html) does the job.

## Manual checklist on the Mac (real mode)

1. Accessibility prompt appears if not granted; after granting + restart, `hello.trusted` is true (no yellow banner on phone).
2. Pointer moves smoothly; speed feels right at default (Settings slider 1.6).
3. Tap = click, tap-tap = double-click (opens a Finder item), two-finger tap = context menu.
4. Two-finger scroll in Safari/Chrome, momentum stops naturally.
5. Double-tap-hold drags a Finder window; holding Left + moving also drags.
6. Keynote / PowerPoint / Google Slides fullscreen: Next/Back, `B` blanks the screen.
7. Laser: `swiftc` compiles on first launch (look for the compile-failed message); dot shows
   **over a fullscreen slideshow**, on the correct display, and hides on release.
8. Volume ±/mute changes Mac volume and the level shows on the phone.
9. Silence: without the Shortcut → instruction toast; with it → Do Not Disturb toggles.
10. Kill Wi-Fi briefly: phone shows Reconnecting… then recovers.

## Backlog (in priority order)

1. **Verify on macOS** (checklist above) and fix the untested parts.
2. **`--tunnel` flag**: start `cloudflared tunnel --url http://localhost:PORT` as a child
   process, parse the `https://*.trycloudflare.com` URL from its output, put it first in
   `urls()` so the QR uses it. Download the binary if missing:
   `https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-{arm64,amd64}.tgz`
   (both assets confirmed to exist on 2026-10-07). Measure added latency with the in-app ms readout.
   Costs: quick-tunnel URL changes every run, so the home-screen shortcut lasts one session.
3. **Android Bluetooth HID app** (alternative to Wi-Fi/tunnel): Android 9+ `BluetoothHidDevice`
   makes the phone a Bluetooth mouse+keyboard; no Mac software, works on any network. Loses
   laser overlay and volume readout (consumer-control volume keys still possible). Needs
   Android Studio/Kotlin. Decide with Sota before starting.
4. Momentum scroll sends ~40 tiny messages after lift; coalesce or cap.
5. WebSocket server ignores fragmented frames (fine for this client; harden if reused).
6. Laser on multi-display setups: verify the Cocoa y-conversion on a secondary display.

## Working with Sota

- Short, conclusion-first reports. Say what was tested vs. not.
- Do the work, then report; don't ask "want me to…?" for things that are clearly in scope.
- For a UI redesign, his preferred flow: define the design system → design screens in Claude
  Design → /design-sync → build here → design skills only as a final QA pass.
