"""Record scroll events (time, lines, pixels, continuous) to stdout until killed."""
import ctypes, ctypes.util, sys, time
cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
CB = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p)
cg.CGEventTapCreate.restype = ctypes.c_void_p
cg.CGEventTapCreate.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint64, CB, ctypes.c_void_p]
cg.CGEventGetIntegerValueField.restype = ctypes.c_int64
cg.CGEventGetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
cg.CGEventGetDoubleValueField.restype = ctypes.c_double
cg.CGEventGetDoubleValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
cf.CFMachPortCreateRunLoopSource.restype = ctypes.c_void_p
cf.CFMachPortCreateRunLoopSource.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
cf.CFRunLoopGetCurrent.restype = ctypes.c_void_p
cf.CFRunLoopAddSource.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
mode = ctypes.c_void_p.in_dll(cf, "kCFRunLoopDefaultMode")
def on(proxy, typ, ev, ref):
    if typ == 22:
        print("%.4f %d %.2f %d %d" % (time.time(),
            cg.CGEventGetIntegerValueField(ev, 11),      # line delta axis 1
            cg.CGEventGetDoubleValueField(ev, 96),        # point delta axis 1
            cg.CGEventGetIntegerValueField(ev, 88),       # is continuous
            cg.CGEventGetIntegerValueField(ev, 12)), flush=True)  # line delta axis 2
    return ev
cb = CB(on)
tap = cg.CGEventTapCreate(0, 0, 1, 1 << 22, cb, None)
src = cf.CFMachPortCreateRunLoopSource(None, tap, 0)
cf.CFRunLoopAddSource(cf.CFRunLoopGetCurrent(), src, mode)
cf.CFRunLoopRun()
