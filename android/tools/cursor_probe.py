"""Poll the Mac cursor at ~2 kHz while an adb swipe runs; report update cadence."""
import ctypes, ctypes.util, subprocess, sys, time, statistics
cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
class P(ctypes.Structure): _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]
cg.CGEventCreate.restype = ctypes.c_void_p; cg.CGEventCreate.argtypes = [ctypes.c_void_p]
cg.CGEventGetLocation.restype = P; cg.CGEventGetLocation.argtypes = [ctypes.c_void_p]
cf.CFRelease.argtypes = [ctypes.c_void_p]
def pos():
    e = cg.CGEventCreate(None); p = cg.CGEventGetLocation(e); cf.CFRelease(e); return p.x, p.y
ADB = "/opt/homebrew/share/android-commandlinetools/platform-tools/adb"
cg.CGWarpMouseCursorPosition.argtypes = [P]
cg.CGMainDisplayID.restype = ctypes.c_uint32
cg.CGDisplayPixelsWide.argtypes = cg.CGDisplayPixelsHigh.argtypes = [ctypes.c_uint32]
d = cg.CGMainDisplayID()
cg.CGWarpMouseCursorPosition(P(cg.CGDisplayPixelsWide(d) * 0.2, cg.CGDisplayPixelsHigh(d) * 0.3))
time.sleep(0.3)
dur = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
swipe = subprocess.Popen([ADB, "shell", "input", "swipe", "300", "1500", "1000", "1600", str(dur)])
t0 = time.perf_counter(); last = pos(); ev = []
while time.perf_counter() - t0 < dur / 1000 + 1.5:
    p = pos()
    if p != last: ev.append((time.perf_counter(), p[0] - last[0], p[1] - last[1])); last = p
    time.sleep(0.0004)
swipe.wait()
if len(ev) < 3: sys.exit("no movement seen (%d updates)" % len(ev))
gaps = [(b[0] - a[0]) * 1000 for a, b in zip(ev, ev[1:])]
steps = [abs(e[1]) + abs(e[2]) for e in ev]
gs = sorted(gaps)
print("updates %d over %.0f ms" % (len(ev), (ev[-1][0] - ev[0][0]) * 1000))
print("gap ms: median %.1f  p90 %.1f  p99 %.1f  max %.1f  stdev %.1f" % (
    statistics.median(gaps), gs[int(.9 * len(gs))], gs[min(len(gs) - 1, int(.99 * len(gs)))], gs[-1], statistics.pstdev(gaps)))
print("gaps > 20 ms: %d" % sum(g > 20 for g in gaps))
print("step px: median %.1f  max %.1f" % (statistics.median(steps), max(steps)))
# What the eye sees: cursor displacement per 120 Hz display frame over the steady middle.
t_a = ev[0][0] + (ev[-1][0] - ev[0][0]) * 0.2
t_b = ev[0][0] + (ev[-1][0] - ev[0][0]) * 0.8
F = 1 / 120.0
frames = []
t = t_a; j = 0
while t < t_b:
    d = 0.0
    while j < len(ev) and ev[j][0] < t + F:
        if ev[j][0] >= t: d += abs(ev[j][1]) + abs(ev[j][2])
        j += 1
    frames.append(d); t += F
m = statistics.mean(frames)
print("per 120Hz frame: frozen %d%%, displacement CV %.2f (lower = smoother)" % (
    100 * sum(f == 0 for f in frames) / len(frames), statistics.pstdev(frames) / m))
