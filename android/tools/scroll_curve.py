"""Drive the phone page's scroll messages at fixed speeds; report Mac output vs input."""
import subprocess, sys, time, ctypes, ctypes.util, json, os
from playwright.sync_api import sync_playwright
S = os.path.dirname(os.path.abspath(__file__))
ADB = "/opt/homebrew/share/android-commandlinetools/platform-tools/adb"
sock = subprocess.check_output([ADB, "shell", "cat /proc/net/unix | grep -o 'webview_devtools_remote_[0-9]*' | sort -u"]).decode().split()[-1]
subprocess.check_call([ADB, "forward", "tcp:9333", "localabstract:" + sock])
cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
class P(ctypes.Structure): _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]
cg.CGWarpMouseCursorPosition.argtypes = [P]
cg.CGWarpMouseCursorPosition(P(700, 8))  # menu bar: nothing scrolls there
rec = subprocess.Popen([sys.executable, os.path.join(S, "scroll_rec.py")], stdout=subprocess.PIPE, text=True)
time.sleep(1)
speeds = [float(a) for a in sys.argv[1:]] or [1, 2, 3, 5, 8, 12, 20, 30]
windows = []
with sync_playwright() as p:
    b = p.chromium.connect_over_cdp("http://127.0.0.1:9333")
    page = b.contexts[0].pages[0]
    for v in speeds:
        t0 = time.time()
        # one message per 16.7 ms frame, like the page's rAF batching; v = CSS px per frame
        page.evaluate("""(v) => new Promise(res => { let acc = 0, n = 0;
            const id = setInterval(() => { acc += v; const d = Math.trunc(acc); acc -= d;
              if (d) LecternNative.post(JSON.stringify({t:'s', dx:0, dy:-d}));
              if (++n >= 72) { clearInterval(id); res(); } }, 16.7); })""", v)
        t1 = time.time()
        windows.append((v, t0, t1))
        time.sleep(1.2)
    b.close()
time.sleep(0.5); rec.terminate()
ev = [tuple(map(float, l.split())) for l in rec.stdout.read().split("\n") if l.strip()]
print("in css px/frame | in css px total | Mac events | lines | pixels | px out per css px in")
for v, t0, t1 in windows:
    w = [e for e in ev if t0 <= e[0] <= t1 + 1.1]
    other = [e for e in w if e[2] > 0]  # ours scroll negative; anything positive is someone else
    if other: print("  (ignored %d foreign events: %s)" % (len(other), [("%+.2fs" % (e[0] - t1), int(e[1]), round(e[2], 1), int(e[3])) for e in other][:8]))
    w = [e for e in w if e[2] <= 0]
    lines = sum(e[1] for e in w); px = sum(e[2] for e in w)
    total = v * 72
    print("%6.1f | %6.0f | %4d | %5.0f | %7.0f | %5.2f" % (v, total, len(w), lines, px, abs(px) / total))
