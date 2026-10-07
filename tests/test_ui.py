"""Phone-UI tests: real touch events (via Chrome DevTools) on a 390x844 mobile viewport.

Needs Playwright:  pip install playwright && python3 -m playwright install chromium
Skipped automatically if Playwright is missing. Screenshots land in tests/screenshots/.
"""
import os
import re
import socket
import subprocess
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "tests", "screenshots")

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class UITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.makedirs(SHOTS, exist_ok=True)
        cls.port = free_port()
        cls.log_path = os.path.join(ROOT, "tests", ".ui-server.log")
        cls.log = open(cls.log_path, "w")
        cls.proc = subprocess.Popen(
            [sys.executable, "-u", os.path.join(ROOT, "lectern.py"), "--dry-run", "--no-browser",
             "--token", "testkey", "--port", str(cls.port)],
            stdout=cls.log, stderr=subprocess.STDOUT)
        time.sleep(1)
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()
        cls.ctx = cls.browser.new_context(viewport={"width": 390, "height": 844},
                                          device_scale_factor=2, has_touch=True, is_mobile=True)
        cls.page = cls.ctx.new_page()
        cls.errors = []
        cls.page.on("pageerror", lambda e: cls.errors.append(str(e)))
        cls.page.goto("http://127.0.0.1:%d/?k=testkey" % cls.port)
        cls.page.wait_for_selector("#dot.on")
        cls.cdp = cls.ctx.new_cdp_session(cls.page)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.proc.terminate()
        cls.proc.wait(5)
        cls.log.close()

    # helpers
    def touch(self, kind, pts):
        self.cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints":
                      [{"x": x, "y": y, "id": i} for i, (x, y) in enumerate(pts)]})

    def events(self, fn):
        """Run fn and return the dry-run lines it caused."""
        time.sleep(0.2)
        with open(self.log_path) as f:
            before = len(f.read())
        fn()
        time.sleep(0.4)
        with open(self.log_path) as f:
            return re.findall(r"\[dry-run\] (.+)", f.read()[before:])

    def center(self, sel):
        b = self.page.locator(sel).bounding_box()
        return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2

    def tab(self, name):
        self.page.locator(".tabs button[data-view=%s]" % name).tap()
        time.sleep(0.2)

    # tests
    def test_1_one_finger_move(self):
        self.tab("pad")
        cx, cy = self.center("#pad")

        def go():
            self.touch("touchStart", [(cx, cy)])
            for i in range(1, 11):
                self.touch("touchMove", [(cx + i * 8, cy + i * 4)])
                time.sleep(0.016)
            self.touch("touchEnd", [])
        ev = self.events(go)
        self.assertTrue(any(e.startswith("move") for e in ev), ev)
        self.assertFalse(any(e.startswith("button") for e in ev), ev)

    def test_2_tap_is_left_click(self):
        cx, cy = self.center("#pad")

        def go():
            self.touch("touchStart", [(cx, cy)])
            time.sleep(0.05)
            self.touch("touchEnd", [])
        self.assertEqual(self.events(go), ["button left down 1", "button left up 1"])
        time.sleep(0.4)  # don't arm double-tap-drag for the next test

    def test_3_two_finger_tap_is_right_click(self):
        cx, cy = self.center("#pad")

        def go():
            self.touch("touchStart", [(cx, cy), (cx + 40, cy)])
            time.sleep(0.05)
            self.touch("touchEnd", [])
        self.assertEqual(self.events(go), ["button right down 1", "button right up 1"])

    def test_4_two_finger_scroll_is_natural(self):
        cx, cy = self.center("#pad")

        def go():
            self.touch("touchStart", [(cx, cy), (cx + 40, cy)])
            for i in range(1, 8):
                self.touch("touchMove", [(cx, cy - i * 10), (cx + 40, cy - i * 10)])
                time.sleep(0.016)
            self.touch("touchEnd", [])
            time.sleep(0.8)  # momentum
        ev = [e for e in self.events(go) if e.startswith("scroll")]
        self.assertTrue(ev)
        self.assertTrue(all(int(e.split()[2]) < 0 for e in ev), ev)  # fingers up -> wheel < 0

    def test_5_double_tap_hold_drags(self):
        cx, cy = self.center("#pad")
        time.sleep(0.4)

        def go():
            self.touch("touchStart", [(cx, cy)])
            time.sleep(0.05)
            self.touch("touchEnd", [])
            time.sleep(0.12)
            self.touch("touchStart", [(cx, cy)])
            for i in range(1, 6):
                self.touch("touchMove", [(cx + i * 10, cy)])
                time.sleep(0.016)
            self.touch("touchEnd", [])
        ev = self.events(go)
        self.assertEqual(ev[:3], ["button left down 1", "button left up 1", "button left down 1"])
        self.assertTrue(any(e.startswith("drag") for e in ev))
        self.assertEqual(ev[-1], "button left up 1")
        self.page.screenshot(path=os.path.join(SHOTS, "trackpad.png"))

    def test_6_next_key(self):
        self.tab("present")
        x, y = self.center(".key.next")

        def go():
            self.touch("touchStart", [(x, y)])
            self.touch("touchEnd", [])
        self.assertEqual(self.events(go), ["key 124 0"])

    def test_7_laser_moves(self):
        self.tab("present")
        x, y = self.center("#laser")

        def go():
            self.touch("touchStart", [(x, y)])
            for i in range(1, 5):
                self.touch("touchMove", [(x + i * 10, y + i * 3)])
                time.sleep(0.02)
            self.page.screenshot(path=os.path.join(SHOTS, "present-laser.png"))
            self.touch("touchEnd", [])
        ev = self.events(go)
        # dry run has no Swift helper, so the laser falls back to moving the cursor
        self.assertGreaterEqual(len([e for e in ev if e.startswith("move")]), 2, ev)

    def test_8_volume(self):
        self.tab("present")
        x, y = self.center("[data-vol=up]")

        def go():
            self.touch("touchStart", [(x, y)])
            self.touch("touchEnd", [])
        self.assertEqual(self.events(go), ["volume up"])
        self.assertEqual(self.page.locator("#lvl").inner_text(), "50")

    def test_9_no_page_errors(self):
        self.page.locator("#gear").tap()
        time.sleep(0.4)
        self.page.screenshot(path=os.path.join(SHOTS, "settings.png"))
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
