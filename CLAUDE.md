# Lectern — handoff notes for Claude Code

Phone-as-trackpad and presentation remote for macOS. Functional equivalent of Mousely
(mouse.ly, seen in an Instagram reel). Copy the *features* only: the name, look, icon and
copy are original and must stay that way.

Owner: Sota. Phone: **Android** (Chrome). Laptop: Mac. Main venue: UC Berkeley, where campus
Wi-Fi blocks phone→laptop traffic (verified 2026-10-07: run with `--tunnel` there).

## Status (verified on Sota's Mac, 2026-10-07)

| Part | Status |
|---|---|
| WebSocket protocol, pairing, HTTP serving | tested (`tests/test_protocol.py`, 15 tests, dry-run) |
| Phone gestures → events | tested (`tests/test_ui.py`, 9 tests, Chromium mobile viewport + CDP touch events) |
| CoreGraphics ctypes calls (`MacBackend`) | verified: bounds, position, pointer move, scroll post correctly on Apple Silicon |
| `laser.swift` overlay | verified: compiles with Xcode swiftc, window lands centred on the requested point at screen-saver level, hides on command |
| osascript volume, Accessibility check | verified |
| `shortcuts run` focus toggle | not verified: no "Lectern Focus" Shortcut exists yet, so the instruction toast path runs |
| `--tunnel` (cloudflared quick tunnel) | verified end to end from campus Wi-Fi; WebSocket ping RTT 50-70 ms |
| `--tunnel` named mode (`https://lectern.<your-domain>`) | verified from the Mac: page, manifest, icons, /pair locked, WebSocket ping RTT 40-50 ms. Set up on Sota's Mac on 2026-10-07 |
| Installable app (manifest + service worker) | verified: installed on Sota's Android via Chrome "Install app" at https://lectern.<your-domain> (2026-10-07) |
| Real Android phone over campus Wi-Fi | **blocked by the network**: UC Berkeley Wi-Fi isolates clients, confirmed. Use `--tunnel` there. |
| Real Android phone over the tunnel | verified: Sota walked the checklist over the quick tunnel, then the named tunnel; smoothing and scroll default tuned to his feel |

## Run and test

```
python3 lectern.py                 # real mode (macOS); opens pairing page with QR
python3 lectern.py --tunnel        # also opens a Cloudflare tunnel; needed on campus Wi-Fi.
                                   # Named (fixed https://lectern.<your-domain>) if
                                   # ~/.config/lectern/tunnel.yml exists, else a quick tunnel
python3 lectern.py --tunnel-setup lectern.<your-domain>   # one-time; needs `cloudflared tunnel login`
python3 lectern.py --no-smooth     # post events on arrival (compare against the Pacer)
python3 lectern.py --dry-run       # logs "[dry-run] ..." instead of posting events; any OS
python3 -m unittest discover -s tests -v   # 25 tests, ~15 s; UI tests skip without Playwright
pip install playwright && python3 -m playwright install chromium   # for tests/test_ui.py
```

## Files

```
lectern.py        server: HTTP + hand-rolled WebSocket (asyncio), Controller, backends
laser.swift       red-dot overlay; compiled by lectern.py with swiftc into ~/.config/lectern/
web/index.html    the whole phone app (HTML+CSS+JS, one file, no build step)
web/pair.html     QR pairing page, served only to a browser on the Mac itself
web/manifest.webmanifest  makes the page installable ("Install app") on Android Chrome over HTTPS
web/sw.js         service worker: caches only the app shell (/, manifest, icons); never /ws
web/icon.png      home-screen icon (original); icon-192/512.png are sips resizes of it
start.command     double-click launcher (terminal)
app/              menu bar app: main.swift, LecternApp.swift (launcher for lectern.py),
                  PhoneLink.swift (Bluetooth helper for the Android app), Info.plist
build-app.sh      builds dist/Lectern.app (universal) with swiftc/sips/iconutil
make-signing-cert.sh  one-time self-signed code-signing identity so rebuilds keep Accessibility
tests/            protocol + UI tests (see above)
android/          Bluetooth HID app (Kotlin, no AndroidX): HidPeripheral.kt (descriptor,
                  register/connect, paced reports), MainActivity.kt (WebView hosting
                  web/index.html + JS bridge). See backlog 3.
```

## Releases

GitHub releases on Rum1324/lectern (public repo: keep hostnames, device names/addresses, domains
out of commits). Assets: `Lectern.app.zip` (`./build-app.sh`, then `ditto -c -k --keepParent
dist/Lectern.app`) and `Lectern-<ver>.apk` (`cd android && ./gradlew assembleRelease`). The APK
release key is `~/.config/lectern/android-release.jks`, passwords in
`~/.config/lectern/android-signing.properties` (both mode 600, never in the repo; back them up:
losing the key means users must uninstall to update). Debug builds (adb) are signed with the
machine's debug key and can't update a release install, or vice versa: uninstall first.
Versions: v0.1.0 web + menu bar app; v0.5.0 Android Bluetooth app + Mac helper (2026-10-09).

## Menu bar app

**Bluetooth helper (PhoneLink.swift, 2026-10-09).** Lectern.app also serves the Android app's
Bluetooth mode. The phone's HID descriptor has a vendor collection (page 0xFF00): input report 4
(8 bytes: type 1 scroll / 2 laser / 3 laser hide / 4 focus, int16 quarter units) and output report
5 (heartbeat the helper sends every 1 s via IOHIDDeviceSetReport; **the buffer must start with
the report ID**, else Android sees report 1). The phone uses report 4 only while heartbeats arrive
(2.5 s timeout), so with Lectern.app quit it falls back to wheel notches / pointer laser.
Helper ports lectern.py's Pacer (120 Hz, alpha 0.5), posts the same pixel scroll events, draws
laser.swift's dot in-process. Needs Input Monitoring (device includes a keyboard) besides
Accessibility; the app requests it at launch, else add it with "+" in Privacy → Input Monitoring.
Verified 2026-10-09: helper scroll exactly 1.00 px/px at all speeds; laser dot at level 1000,
hides on release; quit → phone falls back within ~3 s; relaunch → back. Changing the descriptor
needs re-pairing (Mac: Forget; phone: Unpair; pair again): the Mac caches it.
Rebuild + reinstall kept both TCC grants (designated requirement is the "Lectern Dev" certificate
leaf, not the cdhash): checked by behaviour, not assumed.

`Lectern.app` runs `/usr/bin/python3 -u lectern.py --no-browser --port 8765 [--tunnel]` from its
Resources folder, parses the server's stdout for the address and the Accessibility warning,
logs everything to `~/.config/lectern/app.log`, and SIGTERMs the child on Stop/Quit (3 s grace,
then SIGKILL). lectern.py handles SIGINT/SIGTERM/SIGHUP through `loop.add_signal_handler`
and closes phone connections before the server: raising SystemExit from a plain signal
handler made Python 3.12's `wait_closed()` hang until the phone's 30 s idle timeout. "Use tunnel" is a UserDefaults bool, default on; toggling it
restarts the server. Advanced → "Use my fixed address" (shown only when
~/.config/lectern/tunnel.yml exists, default on) passes `--quick-tunnel` when off, to get the
random address new users get; Sota's installed PWA needs it on. Accessibility must be granted to Lectern.app itself (not Terminal). The grant is keyed to the
code signature: ad-hoc signatures change every build, so `./make-signing-cert.sh` creates a
self-signed "Lectern Dev" identity that build-app.sh uses when present (Sota's Mac has it).
A stuck or stale entry in the Accessibility list: `tccutil reset Accessibility
com.lectern.menubar`, relaunch, grant again. It is not notarized: users
right-click → Open once. Apple's python3 (3.9) is what runs inside the app, hence the 3.9 rule.

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
With `--tunnel`: phone ⇄ Cloudflare edge ⇄ cloudflared (child process, `Tunnel`) ⇄ localhost.
The page is a PWA when served over HTTPS: `manifest.webmanifest` + `sw.js` (shell cache only).
The manifest is served only with `?k=<key>` (the page adds the link after it knows the key)
and its `start_url` is `/?k=<key>`, so the installed app pairs even when the origin's
localStorage is empty at launch (Sota hit "Not paired" with a plain `/` start_url).
The pairing key lives in the phone's localStorage, so the installed app's `start_url` is `/`.
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
- **Jitter smoothing (`Pacer`)**: the Mac does not post each message on arrival. Move, scroll
  and laser deltas go into a per-stream backlog that a 120 Hz asyncio task drains a fraction
  per tick (`Pacer._step`, alpha 0.5). Totals are exact; `flush()` runs synchronously before
  any click/button change so event order is preserved; `--no-smooth` disables it for A/B.
- Momentum scroll on the phone integrates every frame but sends at most ~20 msgs/s and stops
  at 0.08 px/ms (was ~40 msgs per flick).
- Gestures use `targetTouches`, so holding the Left button while moving on the pad works.
- Disconnect releases any held button (`Controller.release_all`).
- Phone keep-awake: Wake Lock needs HTTPS, so over plain LAN HTTP a 1.5 kB muted looping
  video (base64 in index.html) does the job.

## Manual checklist on the Mac (real mode)

1. Accessibility prompt appears if not granted; after granting + restart, `hello.trusted` is true (no yellow banner on phone).
2. Pointer moves smoothly; speed feels right at default (Settings sliders: pointer 1.6, scroll 1.0).
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

1. **Walk the gesture checklist** (items 2-10 above) with the Android phone over `--tunnel`.
2. **Tunnel hardening.** `--tunnel` works (class `Tunnel` in lectern.py). Known rough edges:
   the readiness poll can cache an NXDOMAIN in the Mac's resolver while the edge is still
   propagating (the phone is unaffected); quick-tunnel URL changes every run, so the
   home-screen shortcut lasts one session; `Server._tunnel_failed` warns loudly and continues on LAN.
   Gotcha found the hard way: cloudflared silently loads `~/.cloudflared/config.yml` (Sota has
   one from another project with `tunnel: <other id>` and a catch-all `http_status:404`). That
   file overrides `--url` (every quick tunnel 404s) **and** the tunnel name passed to any
   subcommand (`route dns lectern …` routed to the other tunnel → 1033/530). Lectern therefore
   passes its own `--config` to every cloudflared invocation. Named tunnel `lectern`
   with a CNAME on Sota's own domain exists in his Cloudflare account (hostname kept out of the
   repo on purpose; it is in `~/.config/lectern/tunnel.yml`);
   `~/.config/lectern/tunnel.yml` is rewritten on each run with the current port.
   Cloudflare caches `.js` by extension at the edge; a 530 served during the misroute stayed
   cached for `/sw.js` for a while (cache-busted URL was fine). If "Install app" doesn't
   appear, check `curl -I https://lectern.<your-domain>/sw.js` is 200.
3. **Android Bluetooth HID app** (started 2026-10-09). Android 9+ `BluetoothHidDevice` makes the
   phone a Bluetooth mouse+keyboard: no Mac software, no network, no Cloudflare.
   Decided by Sota (2026-10-09): the native Android app is the whole product for this mode;
   the laser needs a dedicated Mac app, run only when a laser is wanted (`B` is just a key).
   App in `android/` (Homebrew `android-commandlinetools` SDK at
   /opt/homebrew/share/android-commandlinetools, Gradle 9.8.1, AGP 9.4.1; no Android Studio).
   **UI = web/index.html in a WebView** (Sota chose "port the web app's look", 2026-10-09): the
   build copies it into assets; the page sees `window.LecternNative` and sends the same JSON
   messages through it instead of the WebSocket (`body.native`, `.native-only`/`.web-only`).
   In native mode: linear pointer gain (the Mac accelerates HID mice itself), Bluetooth device
   picker in the gate, laser area moves the pointer, Silence shows a toast. Don't pad the WebView
   natively: it already passes system-bar insets to `env(safe-area-inset-*)`.
   HID: combo descriptor (report 1 keyboard, 2 mouse int16 X/Y + wheel + AC Pan, 3 consumer
   volume). `HidPeripheral` paces movement: backlog drained every 7.5 ms, alpha 0.5.
   Build: `cd android && ./gradlew assembleDebug`; install: `adb install -r
   app/build/outputs/apk/debug/app-debug.apk`. Debug hook: `am start -n
   com.lectern.hid/.MainActivity --ei tickUs 5000` overrides the tick.
   Verified on Sota's Xiaomi 14 Ultra (Android 16) + Mac, 2026-10-09: pairs from the Mac
   (System Settings → Bluetooth → Connect), pointer/click/keys work, the app reconnects by itself
   after restarts (6/6 since; one early phone-initiated reconnect showed "connected" on both
   sides but delivered no input, cause unknown, fixed by clicking Connect on the Mac).
   Smoothness, measured with a Mac-side cursor poller + `adb shell input swipe`: the Mac holds
   the link in sniff mode at 7.5-10 ms, so per-touch-event sending (60 Hz) gave 51-77% frozen
   120 Hz frames; paced 7.5 ms gives ~20-30%. A2DP earphones on the Mac share the radio: Sota's
   earphones stutter while the cursor moves, and 5 ms ticks were erratic with audio on.
   Sota confirmed on the phone (2026-10-09): everything works as planned, except scroll feel.
   **Scroll** (fixed 2026-10-09, measured, awaiting Sota's feel test): macOS accelerates wheel
   notches by rate. Measured model (tools/tick_trace.py): a notch >150 ms after the previous one
   = 1 px and resets; otherwise the Mac keeps an EMA of notch spacing (weight 0.24, start 150 ms)
   and a notch = STEADY_PX(EMA), ~10 px at 150 ms to ~94 px at 12 ms. `HidPeripheral.Axis` runs
   that model, backlog in Mac px (1 CSS px -> 1 Mac px; Scroll speed applies in the page), sends a
   notch when backlog >= half the prediction; MODEL_GAIN 1.15 from closed-loop checks. Result:
   0.8x..10x before -> ~1.0-1.1 from 1.5 CSS px/frame up. Below that macOS has nothing between
   1 px and ~10 px notches, so very slow scrolling stays coarse. Curve depends on the Mac's
   scroll-speed setting. HID Resolution Multiplier (hi-res wheel) untested on macOS; would need
   re-pairing (the Mac caches the descriptor).
   Tools in `android/tools/` (Mac side, phone on adb, Lectern open and connected; keep hands off
   the Mac's trackpad): `cursor_probe.py` (pointer smoothness via `adb shell input swipe`),
   `scroll_curve.py` (Mac px out per CSS px in; target flat ~1), `tick_curve.py` / `tick_trace.py`
   (raw notches via bridge message `rawwheel`: px per notch, notch-by-notch ramp). They drive the
   page with Playwright over `adb forward` to `webview_devtools_remote_<pid>` and read scroll
   events with a listen-only event tap.
   **Connection lifecycle** (learned the hard way, 2026-10-09):
   - `registerApp` fails unless the app is foreground ("failed because the app is not
     foreground"), e.g. launched over the lock screen; `start()` is retried on every resume.
   - Process killed without unregistering (Xiaomi kills/freezes background apps) leaves the Mac
     holding a stale HID link: every reconnect gets "A connection to … already exists" until the
     phone is disconnected on the Mac. Hence `LecternService` (foreground service, notification
     with Stop; swiping from Recents stops cleanly) and `Lectern` (process-wide HidPeripheral).
   - Connecting while the Mac is still closing the previous link (reinstall) gave a link both
     sides call connected that delivers nothing (the Mac's IOHIDUserDevice LastActivityTimestamp
     never moves). Fix: wait SETTLE_MS (1.5 s) after registering; tapping the connected Mac in
     the device list does disconnect + reconnect. Verified: 3 reinstalls + force-stop reconnect.
   - Failed attempts retry with backoff (4x); a link the Mac closes later is not reopened.
   Device picker shows only computers (plus the last host). The gate pads for the status bar.
4. Pacer alpha 0.5 felt right to Sota over the tunnel; revisit only if the network changes.
5. WebSocket server ignores fragmented frames (fine for this client; harden if reused).
6. Laser on multi-display setups: verify the Cocoa y-conversion on a secondary display.

## Working with Sota

- Short, conclusion-first reports. Say what was tested vs. not.
- Do the work, then report; don't ask "want me to…?" for things that are clearly in scope.
- For a UI redesign, his preferred flow: define the design system → design screens in Claude
  Design → /design-sync → build here → design skills only as a final QA pass.
