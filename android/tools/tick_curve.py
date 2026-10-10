"""Send single wheel notches at fixed intervals; report Mac pixels per notch for each interval."""
import subprocess, sys, time, ctypes, ctypes.util, os, statistics
from playwright.sync_api import sync_playwright
S = os.path.dirname(os.path.abspath(__file__))
ADB = "/opt/homebrew/share/android-commandlinetools/platform-tools/adb"
sock = subprocess.check_output([ADB, "shell", "cat /proc/net/unix | grep -o 'webview_devtools_remote_[0-9]*' | sort -u"]).decode().split()[-1]
subprocess.check_call([ADB, "forward", "tcp:9333", "localabstract:" + sock], stdout=subprocess.DEVNULL)
cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
class P(ctypes.Structure): _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]
cg.CGWarpMouseCursorPosition.argtypes = [P]
cg.CGWarpMouseCursorPosition(P(700, 8))
rec = subprocess.Popen([sys.executable, os.path.join(S, "scroll_rec.py")], stdout=subprocess.PIPE, text=True)
time.sleep(1)
intervals = [float(a) for a in sys.argv[1:]] or [400, 200, 120, 80, 55, 40, 30, 22, 16, 12, 8]
win = []
with sync_playwright() as p:
    b = p.chromium.connect_over_cdp("http://127.0.0.1:9333")
    page = b.contexts[0].pages[0]
    for iv in intervals:
        n = max(8, int(1500 / iv))
        t0 = time.time()
        # raw notches (bridge message "rawwheel"), bypassing the app's scroll pacing
        page.evaluate("""([iv, n]) => new Promise(res => { let k = 0;
            const id = setInterval(() => { LecternNative.post(JSON.stringify({t:'rawwheel', n:1}));
              if (++k >= n) { clearInterval(id); res(); } }, iv); })""", [iv, n])
        win.append((iv, n, t0, time.time()))
        time.sleep(1.5)
    b.close()
time.sleep(0.5); rec.terminate()
ev = [tuple(map(float, l.split())) for l in rec.stdout.read().split("\n") if l.strip()]
print("interval ms | notches sent | events | lines | px | px/notch (steady half)")
for iv, n, t0, t1 in win:
    w = [e for e in ev if t0 <= e[0] <= t1 + 0.3 and e[2] <= 0]  # ours scroll negative; ignore others
    half = w[len(w) // 2:]
    print("%6.0f | %4d | %4d | %5.0f | %6.0f | %6.1f" % (iv, n, len(w), sum(e[1] for e in w), sum(e[2] for e in w),
          abs(sum(e[2] for e in half)) / max(1, n - n // 2)))
