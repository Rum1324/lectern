"""Like tick_curve.py but prints Mac px for every notch in order, to see how the Mac ramps up."""
import subprocess, sys, time, ctypes, ctypes.util, os
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
intervals = [float(a) for a in sys.argv[1:]] or [240, 175, 150, 120, 100, 70, 40, 20]
win = []
with sync_playwright() as p:
    b = p.chromium.connect_over_cdp("http://127.0.0.1:9333")
    page = b.contexts[0].pages[0]
    for iv in intervals:
        t0 = time.time()
        page.evaluate("""([iv, n]) => new Promise(res => { let k = 0;
            const id = setInterval(() => { LecternNative.post(JSON.stringify({t:'rawwheel', n:1}));
              if (++k >= n) { clearInterval(id); res(); } }, iv); })""", [iv, 14])
        win.append((iv, t0, time.time()))
        time.sleep(1.5)
    b.close()
time.sleep(0.5); rec.terminate()
ev = [tuple(map(float, l.split())) for l in rec.stdout.read().split("\n") if l.strip()]
for iv, t0, t1 in win:
    w = [e for e in ev if t0 <= e[0] <= t1 + 0.3 and e[2] <= 0]
    gaps = [round((b[0] - a[0]) * 1000) for a, b in zip(w, w[1:])]
    print("%4.0f ms: px %s" % (iv, [int(-e[2]) for e in w]))
    print("        gaps %s" % gaps)
