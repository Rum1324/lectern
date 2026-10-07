#!/usr/bin/env python3
"""Lectern: control your Mac from your phone (trackpad + presentation remote).

Zero dependencies. Python 3.9+ (the python3 that ships with macOS Command Line Tools works).
Run:  python3 lectern.py           (then scan the QR code that opens in your browser)
      python3 lectern.py --dry-run (log events instead of moving the mouse; works on any OS)
"""
import argparse
import asyncio
import base64
import ctypes
import ctypes.util
import hashlib
import io
import json
import mimetypes
import os
import platform
import re
import secrets
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tarfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
CONF_DIR = os.path.expanduser("~/.config/lectern")
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# mimetypes doesn't know .webmanifest, and .js must be text/javascript for the service worker
STATIC_TYPES = {".webmanifest": "application/manifest+json", ".js": "text/javascript",
                ".html": "text/html; charset=utf-8"}

# macOS virtual key codes
KEY = {"right": 124, "left": 123, "down": 125, "up": 126, "b": 11, "esc": 53, "space": 49}


# --------------------------------------------------------------------------- backends
class DryRunBackend:
    """Logs every action. Used for testing and on non-macOS systems."""

    def __init__(self):
        self.x, self.y = 960.0, 540.0
        self.w, self.h = 1920.0, 1080.0
        self.log = []

    def _rec(self, *a):
        self.log.append(a)
        print("[dry-run]", *a, flush=True)

    def bounds(self):
        return 0.0, 0.0, self.w, self.h

    def position(self):
        return self.x, self.y

    def move_to(self, x, y, dragging):
        self.x, self.y = x, y
        self._rec("drag" if dragging else "move", round(x), round(y))

    def button(self, which, down, clicks):
        self._rec("button", which, "down" if down else "up", clicks)

    def scroll(self, dx, dy):
        self._rec("scroll", dx, dy)

    def key(self, code, flags=0):
        self._rec("key", code, flags)

    def trusted(self):
        return True


class MacBackend:
    """Posts CoreGraphics events through ctypes. Needs Accessibility permission."""

    class CGPoint(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

    class CGRect(ctypes.Structure):
        pass

    def __init__(self):
        P = self.CGPoint

        class CGSize(ctypes.Structure):
            _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]

        self.CGRect._fields_ = [("origin", P), ("size", CGSize)]
        cg = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        cf = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        ax = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        vp, u32, i32 = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int32

        cg.CGEventCreate.argtypes, cg.CGEventCreate.restype = [vp], vp
        cg.CGEventGetLocation.argtypes, cg.CGEventGetLocation.restype = [vp], P
        cg.CGEventCreateMouseEvent.argtypes = [vp, u32, P, u32]
        cg.CGEventCreateMouseEvent.restype = vp
        cg.CGEventCreateKeyboardEvent.argtypes = [vp, ctypes.c_uint16, ctypes.c_bool]
        cg.CGEventCreateKeyboardEvent.restype = vp
        cg.CGEventCreateScrollWheelEvent2.argtypes = [vp, u32, u32, i32, i32, i32]
        cg.CGEventCreateScrollWheelEvent2.restype = vp
        cg.CGEventSetIntegerValueField.argtypes = [vp, u32, ctypes.c_int64]
        cg.CGEventSetFlags.argtypes = [vp, ctypes.c_uint64]
        cg.CGEventPost.argtypes = [u32, vp]
        cg.CGMainDisplayID.restype = u32
        cg.CGGetActiveDisplayList.argtypes = [u32, ctypes.POINTER(u32), ctypes.POINTER(u32)]
        cg.CGDisplayBounds.argtypes, cg.CGDisplayBounds.restype = [u32], self.CGRect
        cf.CFRelease.argtypes = [vp]
        ax.AXIsProcessTrusted.restype = ctypes.c_bool
        self.cg, self.cf, self.ax = cg, cf, ax

    def trusted(self):
        return bool(self.ax.AXIsProcessTrusted())

    def bounds(self):
        """Union of all active displays, in global top-left coordinates."""
        ids = (ctypes.c_uint32 * 16)()
        n = ctypes.c_uint32(0)
        self.cg.CGGetActiveDisplayList(16, ids, ctypes.byref(n))
        rects = [self.cg.CGDisplayBounds(ids[i]) for i in range(n.value)] or \
            [self.cg.CGDisplayBounds(self.cg.CGMainDisplayID())]
        x0 = min(r.origin.x for r in rects)
        y0 = min(r.origin.y for r in rects)
        x1 = max(r.origin.x + r.size.width for r in rects)
        y1 = max(r.origin.y + r.size.height for r in rects)
        return x0, y0, x1, y1

    def position(self):
        ev = self.cg.CGEventCreate(None)
        p = self.cg.CGEventGetLocation(ev)
        self.cf.CFRelease(ev)
        return p.x, p.y

    def _post(self, ev):
        self.cg.CGEventPost(0, ev)  # kCGHIDEventTap
        self.cf.CFRelease(ev)

    def move_to(self, x, y, dragging):
        # 6 = kCGEventLeftMouseDragged, 5 = kCGEventMouseMoved
        etype = 6 if dragging == "left" else (7 if dragging == "right" else 5)
        btn = 1 if dragging == "right" else 0
        self._post(self.cg.CGEventCreateMouseEvent(None, etype, self.CGPoint(x, y), btn))

    def button(self, which, down, clicks):
        x, y = self.position()
        if which == "left":
            etype, btn = (1 if down else 2), 0
        else:
            etype, btn = (3 if down else 4), 1
        ev = self.cg.CGEventCreateMouseEvent(None, etype, self.CGPoint(x, y), btn)
        self.cg.CGEventSetIntegerValueField(ev, 1, clicks)  # kCGMouseEventClickState
        self._post(ev)

    def scroll(self, dx, dy):
        # unit 0 = pixel; wheel1 = vertical, wheel2 = horizontal
        self._post(self.cg.CGEventCreateScrollWheelEvent2(None, 0, 2, int(dy), int(dx), 0))

    def key(self, code, flags=0):
        for down in (True, False):
            ev = self.cg.CGEventCreateKeyboardEvent(None, code, down)
            if flags:
                self.cg.CGEventSetFlags(ev, flags)
            self._post(ev)


# --------------------------------------------------------------------------- laser dot
class Laser:
    """Red dot drawn by a tiny Swift helper (compiled once). Falls back to moving the cursor."""

    def __init__(self, backend, dry):
        self.backend, self.dry = backend, dry
        self.proc = None
        self.binary = os.path.join(CONF_DIR, "laser-helper")
        self.x = self.y = None
        self.ready = False

    async def prepare(self):
        if self.dry or sys.platform != "darwin":
            return
        src = os.path.join(HERE, "laser.swift")
        fresh = os.path.exists(self.binary) and \
            os.path.getmtime(self.binary) >= os.path.getmtime(src)
        if not fresh:
            os.makedirs(CONF_DIR, exist_ok=True)
            p = await asyncio.create_subprocess_exec(
                "swiftc", "-O", src, "-o", self.binary,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            _, err = await p.communicate()
            if p.returncode != 0:
                print("  laser: Swift compile failed, laser will move the cursor instead.\n   ",
                      err.decode()[-300:].strip())
                return
        self.ready = True

    def _send(self, line):
        if not self.ready:
            return False
        if self.proc is None or self.proc.poll() is not None:
            self.proc = subprocess.Popen([self.binary], stdin=subprocess.PIPE, text=True,
                                         bufsize=1)
        try:
            self.proc.stdin.write(line + "\n")
            return True
        except (BrokenPipeError, OSError):
            self.proc = None
            return False

    def start(self):
        self.x, self.y = self.backend.position()

    def move(self, dx, dy):
        if self.x is None:
            self.start()
        x0, y0, x1, y1 = self.backend.bounds()
        self.x = min(max(self.x + dx, x0), x1 - 1)
        self.y = min(max(self.y + dy, y0), y1 - 1)
        if not self._send("show %.1f %.1f" % (self.x, self.y)):
            self.backend.move_to(self.x, self.y, None)

    def hide(self):
        self._send("hide")
        self.x = self.y = None

    def close(self):
        if self.proc and self.proc.poll() is None:
            self._send("quit")


# --------------------------------------------------------------------------- tunnel
TUNNEL_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
CLOUDFLARED_DL = ("https://github.com/cloudflare/cloudflared/releases/latest/download/"
                  "cloudflared-darwin-%s.tgz")


def parse_tunnel_url(text):
    """First https://*.trycloudflare.com URL in cloudflared's output, or None."""
    m = TUNNEL_URL_RE.search(text)
    return m.group(0) if m else None


NAMED_TUNNEL_CFG = os.path.join(CONF_DIR, "tunnel.yml")
NAMED_TUNNEL = "lectern"


def read_named_tunnel(path=NAMED_TUNNEL_CFG):
    """(tunnel name, hostname, credentials file) from the yml written by --tunnel-setup."""
    try:
        with open(path) as f:
            text = f.read()
    except OSError:
        return None
    name = re.search(r"^tunnel:\s*(\S+)", text, re.M)
    host = re.search(r"^\s*-?\s*hostname:\s*(\S+)", text, re.M)
    cred = re.search(r"^credentials-file:\s*(\S+)", text, re.M)
    return (name.group(1), host.group(1), cred.group(1)) if name and host and cred else None


def write_named_tunnel(name, hostname, cred, port, path=NAMED_TUNNEL_CFG):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("# Written by `lectern.py --tunnel-setup`. Delete to go back to quick tunnels.\n"
                "tunnel: %s\ncredentials-file: %s\ningress:\n"
                "  - hostname: %s\n    service: http://localhost:%d\n"
                "  - service: http_status:404\n" % (name, cred, hostname, port))


class Tunnel:
    """Cloudflare tunnel: a public HTTPS URL that reaches this Mac from any network.

    Needed where the Wi-Fi isolates clients (campus networks), so the phone can't reach the
    laptop directly. Two modes:
    - named (after `--tunnel-setup <hostname>`): fixed https://<hostname>, so the phone can
      install the page as an app once and keep it.
    - quick (fallback): a random *.trycloudflare.com URL that changes every run.
    Adds internet round-trip latency; the phone shows it next to the host name.
    """

    def __init__(self, port):
        self.port = port
        self.proc = None
        self.url = None
        self.named = read_named_tunnel()

    def setup(self, hostname):
        """One-time: create the named tunnel, route DNS, write the config. Needs a
        Cloudflare login (`cloudflared tunnel login`) for a zone that owns `hostname`."""
        # Every subcommand loads ~/.cloudflared/config.yml, and a `tunnel:` key there makes
        # cloudflared act on *that* tunnel whatever name we pass (route dns included), so
        # run them all with a config of our own that has no tunnel key.
        os.makedirs(CONF_DIR, exist_ok=True)
        plain = os.path.join(CONF_DIR, "cloudflared.yml")
        with open(plain, "w") as f:
            f.write("no-autoupdate: true\n")
        cf = [self.binary(), "--config", plain, "tunnel"]
        r = subprocess.run(cf + ["create", NAMED_TUNNEL], capture_output=True, text=True)
        if r.returncode != 0 and "already exists" not in r.stderr + r.stdout:
            raise RuntimeError((r.stderr or r.stdout).strip())
        lst = subprocess.run(cf + ["list", "-o", "json", "-n", NAMED_TUNNEL],
                             capture_output=True, text=True)
        ids = [t["id"] for t in json.loads(lst.stdout or "[]") if t.get("name") == NAMED_TUNNEL]
        if not ids:
            raise RuntimeError("tunnel '%s' not found after create" % NAMED_TUNNEL)
        r = subprocess.run(cf + ["route", "dns", "-f", NAMED_TUNNEL, hostname],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout).strip())
        cred = os.path.expanduser("~/.cloudflared/%s.json" % ids[0])
        write_named_tunnel(NAMED_TUNNEL, hostname, cred, self.port)
        self.named = (NAMED_TUNNEL, hostname, cred)
        return "https://" + hostname

    def binary(self):
        found = shutil.which("cloudflared")
        if found:
            return found
        local = os.path.join(CONF_DIR, "cloudflared")
        if os.path.exists(local):
            return local
        arch = "arm64" if platform.machine() == "arm64" else "amd64"
        print("  tunnel: downloading cloudflared (%s)..." % arch, flush=True)
        data = urllib.request.urlopen(CLOUDFLARED_DL % arch, timeout=120).read()
        os.makedirs(CONF_DIR, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            member = next(m for m in tar.getmembers() if m.name.endswith("cloudflared"))
            with tar.extractfile(member) as f, open(local, "wb") as out:
                out.write(f.read())
        os.chmod(local, 0o755)
        return local

    async def start(self, timeout=40.0):
        """Starts cloudflared and returns the public URL once it answers, or None."""
        try:
            binary = await asyncio.to_thread(self.binary)
        except Exception as e:  # download failed, no network, etc.
            print("  tunnel: cloudflared unavailable:", e, flush=True)
            return None
        if self.named:
            name, hostname, cred = self.named
            # Ingress rules in the config win over --url, so rewrite them for this run's port.
            write_named_tunnel(name, hostname, cred, self.port)
            self.proc = await asyncio.create_subprocess_exec(
                binary, "tunnel", "--config", NAMED_TUNNEL_CFG, "--no-autoupdate", "run", name,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            want = lambda s: "https://" + hostname if "Registered tunnel connection" in s else None
        else:
            # cloudflared silently loads ~/.cloudflared/config.yml if one exists. A named-tunnel
            # config there (with its own ingress rules and a catch-all 404) would override
            # --url and every request through the quick tunnel would 404, so give it our own.
            os.makedirs(CONF_DIR, exist_ok=True)
            cfg = os.path.join(CONF_DIR, "cloudflared.yml")
            with open(cfg, "w") as f:
                f.write("url: http://localhost:%d\n" % self.port)
            self.proc = await asyncio.create_subprocess_exec(
                binary, "tunnel", "--config", cfg, "--no-autoupdate",
                "--url", "http://localhost:%d" % self.port,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            want = parse_tunnel_url
        deadline = time.monotonic() + timeout
        while self.url is None and time.monotonic() < deadline:
            try:
                line = await asyncio.wait_for(self.proc.stderr.readline(),
                                              deadline - time.monotonic())
            except asyncio.TimeoutError:
                break
            if not line:
                break
            self.url = want(line.decode("utf-8", "replace"))
        if self.url is None:
            self.close()
            return None
        # Keep draining stderr for the life of the process, or cloudflared blocks on a full pipe.
        asyncio.ensure_future(self._drain())
        # The edge takes a few seconds to route the new hostname; wait until it answers so
        # the QR code isn't scanned into a Cloudflare error page.
        while time.monotonic() < deadline:
            if await asyncio.to_thread(self._answers):
                return self.url
            await asyncio.sleep(1)
        return self.url  # routed late; the phone page retries on its own

    async def _drain(self):
        while await self.proc.stderr.readline():
            pass

    def _answers(self):
        try:
            with urllib.request.urlopen(self.url + "/icon.png", timeout=5) as r:
                return r.status == 200
        except Exception:
            return False

    def close(self):
        proc, self.proc, self.url = self.proc, None, None
        if proc and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass


# --------------------------------------------------------------------------- pacing
class Pacer:
    """Turns bursty deltas into steady ~120 Hz steps.

    Over a tunnel, messages that left the phone 16 ms apart arrive bunched; posting each one on
    arrival makes the pointer freeze and jump. Pending motion is drained a fraction per tick
    instead, which hides jitter at the cost of about one frame of lag. The running total is
    exact: every delta added is eventually emitted, so clicks land where the finger stopped.
    """

    HZ = 120

    def __init__(self, emit, integer=False, alpha=0.5):
        self.emit = emit              # emit(dx, dy)
        self.integer = integer        # scroll wheels take whole pixels
        self.alpha = alpha            # fraction of the backlog released per tick
        self.x = self.y = 0.0
        self.task = None

    def add(self, dx, dy):
        self.x += dx
        self.y += dy
        if self.task is None or self.task.done():
            self.task = asyncio.ensure_future(self._run())

    def flush(self):
        """Emit everything pending now (before a click, so order is preserved)."""
        if self.x or self.y:
            x, y = self.x, self.y
            self.x = self.y = 0.0
            self.emit(x, y)

    def drop(self):
        self.x = self.y = 0.0

    def _step(self):
        """How much of the backlog to release this tick."""
        # alpha=0.5 drains a burst in ~4 ticks (33 ms); Sota found it fine over the tunnel.
        # If tuning: keep the invariant that the last step empties the backlog exactly, or the
        # pointer settles short of where the finger stopped.
        dx, dy = self.x * self.alpha, self.y * self.alpha
        if self.integer:
            dx, dy = float(int(dx)), float(int(dy))
            if (dx == 0 and dy == 0) or max(abs(self.x), abs(self.y)) < 2:
                dx, dy = self.x, self.y
        elif max(abs(self.x), abs(self.y)) < 1:
            dx, dy = self.x, self.y
        return dx, dy

    async def _run(self):
        while self.x or self.y:
            dx, dy = self._step()
            self.x -= dx
            self.y -= dy
            if abs(self.x) < 1e-9:
                self.x = 0.0
            if abs(self.y) < 1e-9:
                self.y = 0.0
            self.emit(dx, dy)
            await asyncio.sleep(1 / self.HZ)


# --------------------------------------------------------------------------- controller
class Controller:
    def __init__(self, backend, laser, smooth=True):
        self.b = backend
        self.laser = laser
        self.held = None          # "left" / "right" while a button is held
        self.last_click = (0.0, 0.0, 0.0, 0)  # time, x, y, count
        self.smooth = smooth
        self.pace_move = Pacer(self._move_now)
        self.pace_scroll = Pacer(lambda dx, dy: self.b.scroll(int(dx), int(dy)), integer=True)
        self.pace_laser = Pacer(self.laser.move)

    def _clicks(self):
        """macOS only treats a click as a double-click if clickState says so."""
        t = time.monotonic()
        x, y = self.b.position()
        lt, lx, ly, n = self.last_click
        n = n + 1 if (t - lt < 0.45 and abs(x - lx) < 6 and abs(y - ly) < 6) else 1
        self.last_click = (t, x, y, n)
        return n

    def _move_now(self, dx, dy):
        x, y = self.b.position()
        x0, y0, x1, y1 = self.b.bounds()
        nx = min(max(x + dx, x0), x1 - 1)
        ny = min(max(y + dy, y0), y1 - 1)
        self.b.move_to(nx, ny, self.held)

    def move(self, dx, dy):
        if self.smooth:
            self.pace_move.add(dx, dy)
        else:
            self._move_now(dx, dy)

    def scroll(self, dx, dy):
        if self.smooth:
            self.pace_scroll.add(dx, dy)
        else:
            self.b.scroll(int(dx), int(dy))

    def laser_move(self, dx, dy):
        if self.smooth:
            self.pace_laser.add(dx, dy)
        else:
            self.laser.move(dx, dy)

    def laser_hide(self):
        self.pace_laser.drop()
        self.laser.hide()

    def click(self, which):
        self.pace_move.flush()
        n = self._clicks() if which == "left" else 1
        self.b.button(which, True, n)
        self.b.button(which, False, n)

    def press(self, which, down):
        self.pace_move.flush()
        if down:
            if self.held:
                return
            # A held press starts a drag; clickState 1 so a recent tap doesn't turn it into
            # a double/triple-click (which would select words or lines instead of dragging).
            self.held = which
            self.last_click = (0.0, 0.0, 0.0, 0)
            self.b.button(which, True, 1)
        elif self.held == which:
            self.b.button(which, False, 1)
            self.held = None

    def release_all(self):
        self.pace_move.flush()
        self.pace_scroll.flush()
        if self.held:
            self.press(self.held, False)
        self.laser_hide()


async def osa(script):
    p = await asyncio.create_subprocess_exec(
        "osascript", "-e", script,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await p.communicate()
    return p.returncode, out.decode().strip(), err.decode().strip()


async def volume(action, dry):
    if dry or sys.platform != "darwin":
        print("[dry-run] volume", action, flush=True)
        return {"t": "vol", "level": 50, "muted": False}
    scripts = {
        "up": "set volume output volume ((output volume of (get volume settings)) + 6)",
        "down": "set volume output volume ((output volume of (get volume settings)) - 6)",
        "mute": "set volume output muted (not (output muted of (get volume settings)))",
        "get": "",
    }
    s = scripts.get(action)
    if s is None:
        return None
    if s:
        await osa(s)
    rc, out, _ = await osa(
        'set s to get volume settings\nreturn ((output volume of s) as text) & "," & '
        '((output muted of s) as text)')
    try:
        lvl, muted = out.split(",")
        return {"t": "vol", "level": int(lvl), "muted": muted == "true"}
    except ValueError:
        return None


async def focus_toggle(dry):
    """macOS has no API to toggle Do Not Disturb; this runs a user-made Shortcut."""
    if dry or sys.platform != "darwin":
        print("[dry-run] focus toggle", flush=True)
        return {"t": "note", "text": "Focus toggled (dry run)"}
    p = await asyncio.create_subprocess_exec(
        "shortcuts", "run", "Lectern Focus",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, err = await p.communicate()
    if p.returncode == 0:
        return {"t": "note", "text": "Focus toggled"}
    return {"t": "note", "text": "Create a Shortcut named “Lectern Focus” on your Mac "
                                 "(Set Focus → Do Not Disturb → Toggle)."}


# --------------------------------------------------------------------------- websocket
async def ws_send(writer, obj):
    data = json.dumps(obj).encode()
    n = len(data)
    if n < 126:
        head = struct.pack("!BB", 0x81, n)
    elif n < 65536:
        head = struct.pack("!BBH", 0x81, 126, n)
    else:
        head = struct.pack("!BBQ", 0x81, 127, n)
    writer.write(head + data)
    await writer.drain()


async def ws_recv(reader):
    """Returns (opcode, payload bytes)."""
    b1, b2 = await reader.readexactly(2)
    op, masked, n = b1 & 0x0F, b2 & 0x80, b2 & 0x7F
    if n == 126:
        n = struct.unpack("!H", await reader.readexactly(2))[0]
    elif n == 127:
        n = struct.unpack("!Q", await reader.readexactly(8))[0]
    if n > 1 << 20:
        raise ConnectionError("frame too large")
    mask = await reader.readexactly(4) if masked else b"\0\0\0\0"
    data = bytearray(await reader.readexactly(n))
    for i in range(n):
        data[i] ^= mask[i & 3]
    return op, bytes(data)


# --------------------------------------------------------------------------- server
class Server:
    def __init__(self, args):
        self.args = args
        self.dry = args.dry_run or sys.platform != "darwin"
        self.backend = DryRunBackend() if self.dry else MacBackend()
        self.laser = Laser(self.backend, self.dry)
        self.ctl = Controller(self.backend, self.laser, smooth=not args.no_smooth)
        self.token = self._load_token()
        self.clients = set()
        self.tunnel = Tunnel(args.port) if args.tunnel else None

    def _load_token(self):
        if self.args.token:
            return self.args.token
        path = os.path.join(CONF_DIR, "token")
        try:
            with open(path) as f:
                t = f.read().strip()
                if t:
                    return t
        except OSError:
            pass
        os.makedirs(CONF_DIR, exist_ok=True)
        t = secrets.token_urlsafe(9)
        with open(path, "w") as f:
            f.write(t)
        os.chmod(path, 0o600)
        return t

    # ---- http
    async def handle(self, reader, writer):
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
        except Exception:
            writer.close()
            return
        lines = head.decode("latin-1").split("\r\n")
        try:
            method, target, _ = lines[0].split(" ", 2)
        except ValueError:
            writer.close()
            return
        headers = {}
        for ln in lines[1:]:
            if ":" in ln:
                k, v = ln.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        path, _, query = target.partition("?")
        params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)

        if path == "/ws" and headers.get("upgrade", "").lower() == "websocket":
            if not secrets.compare_digest(params.get("k", ""), self.token):
                await self._respond(writer, 403, b"bad pairing key", "text/plain")
                return
            await self._websocket(reader, writer, headers)
            return

        # The pairing page shows the key, so it is served only to a browser on this Mac.
        # A tunnel or reverse proxy also connects from 127.0.0.1, so loopback alone is not
        # enough: require a localhost Host header and no forwarding headers as well.
        peer = writer.get_extra_info("peername")
        host = headers.get("host", "").rsplit(":", 1)[0].strip("[]")
        forwarded = any(h in headers for h in
                        ("x-forwarded-for", "forwarded", "cf-connecting-ip", "cf-ray",
                         "x-real-ip"))
        local = bool(peer) and peer[0] in ("127.0.0.1", "::1") and \
            host in ("127.0.0.1", "localhost", "::1") and not forwarded
        if path == "/pair" and local:
            await self._respond(writer, 200, self._pair_page(), "text/html; charset=utf-8")
            return
        if path == "/pair.json" and local:
            body = json.dumps({"urls": self.urls(), "key": self.token}).encode()
            await self._respond(writer, 200, body, "application/json")
            return
        # The installed app launches start_url, so it must carry the pairing key; serve the
        # manifest only to a page that already has the key, so the key never leaks via it.
        if path == "/manifest.webmanifest":
            if not secrets.compare_digest(params.get("k", ""), self.token):
                await self._respond(writer, 404, b"not found", "text/plain")
                return
            with open(os.path.join(WEB, "manifest.webmanifest")) as f:
                manifest = json.load(f)
            manifest["start_url"] = "/?k=" + self.token
            await self._respond(writer, 200, json.dumps(manifest).encode(),
                                "application/manifest+json")
            return
        if path in ("/", "/index.html"):
            path = "/index.html"
        fp = os.path.normpath(os.path.join(WEB, path.lstrip("/")))
        if not fp.startswith(WEB + os.sep) or not os.path.isfile(fp) or \
                os.path.basename(fp) == "pair.html":
            await self._respond(writer, 404, b"not found", "text/plain")
            return
        with open(fp, "rb") as f:
            body = f.read()
        ctype = STATIC_TYPES.get(os.path.splitext(fp)[1]) or \
            mimetypes.guess_type(fp)[0] or "application/octet-stream"
        await self._respond(writer, 200, body, ctype)

    async def _respond(self, writer, code, body, ctype):
        reason = {200: "OK", 403: "Forbidden", 404: "Not Found"}.get(code, "OK")
        writer.write(("HTTP/1.1 %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n"
                      "Cache-Control: no-store\r\nConnection: close\r\n\r\n"
                      % (code, reason, ctype, len(body))).encode() + body)
        try:
            await writer.drain()
        finally:
            writer.close()

    def _pair_page(self):
        with open(os.path.join(WEB, "pair.html"), "rb") as f:
            return f.read()

    # ---- websocket session
    async def _websocket(self, reader, writer, headers):
        key = headers.get("sec-websocket-key", "")
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        writer.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                      "Connection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n"
                      % accept).encode())
        await writer.drain()
        sock = writer.get_extra_info("socket")
        if sock is not None:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        peer = writer.get_extra_info("peername")
        print("  phone connected:", peer[0] if peer else "?", flush=True)
        self.clients.add(writer)
        await ws_send(writer, {"t": "hello", "host": mac_name(),
                               "trusted": self.backend.trusted()})
        v = await volume("get", self.dry)
        if v:
            await ws_send(writer, v)
        try:
            while True:
                op, data = await asyncio.wait_for(ws_recv(reader), 30)
                if op == 0x8:      # close
                    break
                if op == 0x9:      # ping -> pong
                    writer.write(struct.pack("!BB", 0x8A, len(data)) + data)
                    continue
                if op != 0x1:
                    continue
                try:
                    msg = json.loads(data)
                except ValueError:
                    continue
                reply = await self.dispatch(msg)
                if reply:
                    await ws_send(writer, reply)
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.TimeoutError, OSError):
            pass
        finally:
            self.ctl.release_all()
            self.clients.discard(writer)
            print("  phone disconnected", flush=True)
            writer.close()

    async def dispatch(self, m):
        t = m.get("t")
        c = self.ctl
        if t == "m":
            c.move(float(m.get("dx", 0)), float(m.get("dy", 0)))
        elif t == "click":
            c.click("right" if m.get("b") == "right" else "left")
        elif t == "btn":
            c.press("right" if m.get("b") == "right" else "left", bool(m.get("down")))
        elif t == "s":
            c.scroll(round(float(m.get("dx", 0))), round(float(m.get("dy", 0))))
        elif t == "key":
            code = KEY.get(m.get("k"))
            if code is not None:
                c.b.key(code)
        elif t == "laser":
            if m.get("on") is False:
                c.laser_hide()
            else:
                c.laser_move(float(m.get("dx", 0)), float(m.get("dy", 0)))
        elif t == "vol":
            return await volume(m.get("a", "get"), self.dry)
        elif t == "focus":
            return await focus_toggle(self.dry)
        elif t == "ping":
            return {"t": "pong", "id": m.get("id")}
        return None

    # ---- addresses
    def urls(self):
        port, k = self.args.port, self.token
        out = []
        if self.tunnel and self.tunnel.url:
            out.append("%s/?k=%s" % (self.tunnel.url, k))
        for ip in lan_ips():
            out.append("http://%s:%d/?k=%s" % (ip, port, k))
        # name.local survives IP changes but some Android versions can't resolve it, so it's 2nd
        if sys.platform == "darwin":
            try:
                name = subprocess.run(["scutil", "--get", "LocalHostName"],
                                      capture_output=True, text=True).stdout.strip()
                if name:
                    out.append("http://%s.local:%d/?k=%s" % (name, port, k))
            except OSError:
                pass
        return out

    def _tunnel_failed(self):
        """--tunnel was requested but no public URL came up: say so loudly, keep LAN."""
        print("\n  ! tunnel: no public URL after 40 s. The LAN addresses below only work on"
              "\n    networks that let phones talk to laptops (not campus Wi-Fi). Likely causes:"
              "\n    no internet yet, github.com blocked (cloudflared download), or cloudflared"
              "\n    crashed. Fix and restart Lectern.\n", flush=True)

    async def run(self):
        srv = await asyncio.start_server(self.handle, self.args.host, self.args.port)
        await self.laser.prepare()
        if self.tunnel:
            print("  tunnel: starting cloudflared...", flush=True)
            if await self.tunnel.start() is None:
                self._tunnel_failed()
        print("\nLectern is running%s." % (" (dry run: nothing is moved)" if self.dry else ""))
        for u in self.urls():
            print("  open on your phone:", u)
        if not self.dry and not self.backend.trusted():
            print("\n  ! macOS has not granted Accessibility to this terminal app, so clicks and"
                  "\n    keys will be ignored. Turn it on in the pane that just opened, then"
                  "\n    restart Lectern.")
            subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security"
                                    "?Privacy_Accessibility"])
        if not self.args.no_browser and sys.platform == "darwin":
            subprocess.run(["open", "http://127.0.0.1:%d/pair" % self.args.port])
        print("\n  Ctrl+C to stop.\n", flush=True)
        # Stop on Ctrl+C, kill, or the terminal window closing. Handled by the loop (not by
        # raising from a signal handler) so shutdown is orderly: close the phone connections
        # first, or Python 3.12's wait_closed() would wait for them to time out.
        loop = asyncio.get_running_loop()
        stop = loop.create_future()
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            loop.add_signal_handler(sig, lambda: stop.done() or stop.set_result(None))
        try:
            async with srv:
                await stop
                for w in list(self.clients):
                    w.close()
        finally:
            self.laser.close()
            if self.tunnel:
                self.tunnel.close()


def mac_name():
    """The name from System Settings; gethostname() gives the DHCP name on campus Wi-Fi."""
    if sys.platform == "darwin":
        try:
            name = subprocess.run(["scutil", "--get", "ComputerName"],
                                  capture_output=True, text=True).stdout.strip()
            if name:
                return name
        except OSError:
            pass
    return socket.gethostname()


def lan_ips():
    ips = []
    try:  # address of the interface that carries the default route
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    if sys.platform == "darwin":
        for iface in ("en0", "en1", "bridge100"):
            try:
                ip = subprocess.run(["ipconfig", "getifaddr", iface], capture_output=True,
                                    text=True).stdout.strip()
                if ip and ip not in ips:
                    ips.append(ip)
            except OSError:
                pass
    return [i for i in ips if not i.startswith("127.")]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--dry-run", action="store_true", help="log events instead of acting")
    ap.add_argument("--token", help="override the saved pairing key")
    ap.add_argument("--no-browser", action="store_true", help="don't open the QR page")
    ap.add_argument("--no-smooth", action="store_true",
                    help="post each phone message as it arrives (no jitter smoothing)")
    ap.add_argument("--tunnel", action="store_true",
                    help="expose over a Cloudflare tunnel (for Wi-Fi that isolates clients); "
                         "named if --tunnel-setup was run, else a quick tunnel")
    ap.add_argument("--tunnel-setup", metavar="HOSTNAME",
                    help="one-time: create named tunnel 'lectern' routed to HOSTNAME (needs "
                         "`cloudflared tunnel login` first), then exit")
    args = ap.parse_args()
    if args.tunnel_setup:
        try:
            url = Tunnel(args.port).setup(args.tunnel_setup)
        except Exception as e:
            sys.exit("tunnel setup failed: %s" % e)
        print("Named tunnel ready. Run `python3 lectern.py --tunnel`; the QR will show", url)
        return
    server = Server(args)
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:  # only if it lands before the loop installs its handlers
        pass
    finally:
        server.laser.close()
        if server.tunnel:
            server.tunnel.close()


if __name__ == "__main__":
    main()
