"""Protocol tests: start lectern.py in --dry-run mode and drive it over a raw WebSocket.

Runs anywhere (no macOS needed, no dependencies):  python3 -m unittest discover tests
Checks what the server *would* post to macOS, by parsing its "[dry-run] ..." log lines.
"""
import base64
import json
import os
import re
import socket
import struct
import subprocess
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = "testkey"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class WS:
    """Minimal WebSocket client (masked text frames only)."""

    def __init__(self, port, key=KEY):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=3)
        k = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall(("GET /ws?k=%s HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\n"
                        "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
                        "Sec-WebSocket-Version: 13\r\n\r\n" % (key, k)).encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.s.recv(1)
            if not chunk:
                break
            head += chunk
        self.status = int(head.split(b" ")[1]) if head else 0

    def send(self, obj):
        data = json.dumps(obj).encode()
        n = len(data)
        head = struct.pack("!B", 0x81)
        if n < 126:
            head += struct.pack("!B", 0x80 | n)
        elif n < 65536:
            head += struct.pack("!BH", 0x80 | 126, n)
        else:
            head += struct.pack("!BQ", 0x80 | 127, n)
        mask = os.urandom(4)
        self.s.sendall(head + mask + bytes(b ^ mask[i & 3] for i, b in enumerate(data)))

    def recv(self):
        def exact(n):
            buf = b""
            while len(buf) < n:
                c = self.s.recv(n - len(buf))
                if not c:
                    raise ConnectionError
                buf += c
            return buf
        b1, b2 = exact(2)
        n = b2 & 0x7F
        if n == 126:
            n = struct.unpack("!H", exact(2))[0]
        elif n == 127:
            n = struct.unpack("!Q", exact(8))[0]
        return json.loads(exact(n))

    def recv_until(self, t, limit=10):
        for _ in range(limit):
            m = self.recv()
            if m.get("t") == t:
                return m
        raise AssertionError("no %r reply" % t)

    def close(self):
        try:
            self.s.sendall(struct.pack("!BB", 0x88, 0x80) + os.urandom(4))
        finally:
            self.s.close()


class ProtocolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.log_path = os.path.join(ROOT, "tests", ".server.log")
        cls.log = open(cls.log_path, "w")
        cls.proc = subprocess.Popen(
            [sys.executable, "-u", os.path.join(ROOT, "lectern.py"), "--dry-run", "--no-browser",
             "--token", KEY, "--port", str(cls.port)], stdout=cls.log, stderr=subprocess.STDOUT)
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", cls.port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        cls.log.close()

    def events_after(self, mark):
        """Dry-run lines logged after the given marker."""
        time.sleep(0.3)
        with open(self.log_path) as f:
            text = f.read()
        text = text.split(mark, 1)[1] if mark in text else ""
        return re.findall(r"\[dry-run\] (.+)", text)

    def run_session(self, msgs):
        ws = WS(self.port)
        self.assertEqual(ws.status, 101)
        ws.recv_until("hello")
        mark = "MARK-%f" % time.time()
        ws.send({"t": "key", "k": mark})  # unknown key: ignored, but marks the log position
        print(mark, file=self.log, flush=True)
        for m in msgs:
            ws.send(m)
        ws.send({"t": "ping"})
        ws.recv_until("pong")
        return ws, mark

    def test_bad_key_rejected(self):
        ws = WS(self.port, key="wrong")
        ws.s.close()
        self.assertEqual(ws.status, 403)

    def test_move_and_clamp(self):
        ws, mark = self.run_session([{"t": "m", "dx": 1e6, "dy": 1e6}])
        ws.close()
        self.assertIn("move 1919 1079", self.events_after(mark))

    def test_double_click_sets_click_state(self):
        ws, mark = self.run_session([{"t": "click", "b": "left"}, {"t": "click", "b": "left"}])
        ws.close()
        ev = [e for e in self.events_after(mark) if e.startswith("button")]
        self.assertEqual(ev[:4], ["button left down 1", "button left up 1",
                                  "button left down 2", "button left up 2"])

    def test_drag_uses_click_state_1_and_drag_events(self):
        ws, mark = self.run_session([{"t": "click", "b": "left"},
                                     {"t": "btn", "b": "left", "down": True},
                                     {"t": "m", "dx": 5, "dy": 0},
                                     {"t": "btn", "b": "left", "down": False}])
        ws.close()
        ev = self.events_after(mark)
        self.assertIn("button left down 1", ev[2:])
        self.assertTrue(any(e.startswith("drag ") for e in ev))

    def test_disconnect_releases_held_button(self):
        ws, mark = self.run_session([{"t": "btn", "b": "left", "down": True}])
        ws.close()
        time.sleep(0.3)
        self.assertEqual(self.events_after(mark)[-1], "button left up 1")

    def test_right_click_scroll_keys(self):
        ws, mark = self.run_session([{"t": "click", "b": "right"},
                                     {"t": "s", "dx": 0, "dy": -12},
                                     {"t": "key", "k": "right"}, {"t": "key", "k": "b"}])
        ws.close()
        ev = self.events_after(mark)
        for want in ("button right down 1", "key 124 0", "key 11 0"):
            self.assertIn(want, ev)
        # The pacer may split one scroll message into several steps; the total is exact.
        scrolls = [e.split() for e in ev if e.startswith("scroll")]
        self.assertEqual(sum(int(s[2]) for s in scrolls), -12)
        self.assertTrue(all(int(s[2]) < 0 for s in scrolls), scrolls)

    def test_volume_and_focus_reply(self):
        ws, _ = self.run_session([])
        ws.send({"t": "vol", "a": "up"})
        self.assertEqual(ws.recv_until("vol")["level"], 50)
        ws.send({"t": "focus"})
        self.assertEqual(ws.recv_until("note")["t"], "note")
        ws.close()

    def test_large_frame(self):
        ws, _ = self.run_session([])
        ws.send({"t": "ping", "pad": "x" * 300})
        ws.recv_until("pong")
        ws.close()

    def http(self, path, headers=None):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        h = {"Host": "127.0.0.1:%d" % self.port}
        h.update(headers or {})
        s.sendall(("GET %s HTTP/1.1\r\n%s\r\n" % (
            path, "".join("%s: %s\r\n" % kv for kv in h.items()))).encode())
        data = b""
        while True:
            c = s.recv(65536)
            if not c:
                break
            data += c
        s.close()
        self.last_headers = data.split(b"\r\n\r\n", 1)[0].decode("latin-1").lower()
        self.last_body = data.split(b"\r\n\r\n", 1)[1].decode("utf-8", "replace")
        return int(data.split(b" ")[1])

    def test_app_manifest_and_service_worker_types(self):
        self.assertEqual(self.http("/manifest.webmanifest"), 404)  # key required
        self.assertEqual(self.http("/manifest.webmanifest?k=wrong"), 404)
        self.assertEqual(self.http("/manifest.webmanifest?k=" + KEY), 200)
        self.assertIn("content-type: application/manifest+json", self.last_headers)
        self.assertIn('"start_url": "/?k=%s"' % KEY, self.last_body)
        self.assertEqual(self.http("/sw.js"), 200)
        self.assertIn("content-type: text/javascript", self.last_headers)
        self.assertEqual(self.http("/icon-512.png"), 200)

    def test_static_and_traversal(self):
        self.assertEqual(self.http("/"), 200)
        self.assertEqual(self.http("/icon.png"), 200)
        self.assertEqual(self.http("/../lectern.py"), 404)
        self.assertEqual(self.http("/pair.html"), 404)

    def test_pairing_key_hidden_from_proxies(self):
        self.assertEqual(self.http("/pair.json"), 200)
        self.assertEqual(self.http("/pair.json", {"Host": "x.trycloudflare.com"}), 404)
        self.assertEqual(self.http("/pair.json", {"Cf-Connecting-Ip": "1.2.3.4"}), 404)
        self.assertEqual(self.http("/pair", {"X-Forwarded-For": "1.2.3.4"}), 404)


if __name__ == "__main__":
    unittest.main()


class TunnelTest(unittest.TestCase):
    """Pure-function checks for the cloudflared quick-tunnel support (no network)."""

    def setUp(self):
        sys.path.insert(0, ROOT)
        import lectern
        self.lectern = lectern

    def test_parse_url_from_cloudflared_banner(self):
        line = ("2026-10-07T17:00:00Z INF |  https://quiet-river-tulip-sky.trycloudflare.com"
                "                                   |")
        self.assertEqual(self.lectern.parse_tunnel_url(line),
                         "https://quiet-river-tulip-sky.trycloudflare.com")
        self.assertIsNone(self.lectern.parse_tunnel_url("INF Registered tunnel connection"))

    def test_quick_flag_ignores_named_tunnel(self):
        self.assertIsNone(self.lectern.Tunnel(1, quick=True).named)

    def test_tunnel_url_comes_first_in_pairing_urls(self):
        import argparse
        a = argparse.Namespace(port=1, token="K", dry_run=True, host="0.0.0.0",
                               no_browser=True, tunnel=True, no_smooth=False)
        s = self.lectern.Server(a)
        s.tunnel.url = "https://a-b-c-d.trycloudflare.com"
        self.assertEqual(s.urls()[0], "https://a-b-c-d.trycloudflare.com/?k=K")


class PacerTest(unittest.TestCase):
    """The smoother must emit exactly what it was given, in order, and flush before clicks."""

    def setUp(self):
        sys.path.insert(0, ROOT)
        import lectern
        self.lectern = lectern

    def _collect(self, integer, adds):
        import asyncio
        out = []

        async def go():
            p = self.lectern.Pacer(lambda dx, dy: out.append((dx, dy)), integer=integer)
            for dx, dy in adds:
                p.add(dx, dy)
            await asyncio.sleep(0.25)
            self.assertEqual((p.x, p.y), (0.0, 0.0))
        asyncio.run(go())
        return out

    def test_float_total_is_exact_and_split(self):
        out = self._collect(False, [(10.0, -4.0), (10.0, -4.0), (10.0, -4.0)])
        self.assertGreater(len(out), 1)
        self.assertAlmostEqual(sum(d[0] for d in out), 30.0)
        self.assertAlmostEqual(sum(d[1] for d in out), -12.0)

    def test_integer_steps_sum_exactly(self):
        out = self._collect(True, [(0, -12), (0, -12)])
        self.assertTrue(all(d[1] == int(d[1]) for d in out))
        self.assertEqual(sum(d[1] for d in out), -24)
        self.assertTrue(all(d[1] < 0 for d in out), out)

    def test_flush_emits_pending_synchronously(self):
        out = []
        p = self.lectern.Pacer(lambda dx, dy: out.append((dx, dy)))
        p.x, p.y = 3.0, 4.0
        p.flush()
        self.assertEqual(out, [(3.0, 4.0)])
        self.assertEqual((p.x, p.y), (0.0, 0.0))
