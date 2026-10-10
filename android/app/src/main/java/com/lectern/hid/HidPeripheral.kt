package com.lectern.hid

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothHidDevice
import android.bluetooth.BluetoothHidDeviceAppSdpSettings
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.content.Context
import android.os.Handler
import android.os.Looper
import kotlin.math.abs

/**
 * The phone as a Bluetooth HID combo device. Report 1 is a keyboard, 2 a relative mouse with
 * 16-bit X/Y, wheel and horizontal pan, 3 consumer-control keys (volume).
 * All callbacks run on the main thread.
 */
@SuppressLint("MissingPermission") // MainActivity gets BLUETOOTH_CONNECT before start()
class HidPeripheral(private val ctx: Context, private val onChange: () -> Unit) {
    /** off, ready, connecting, connected, disconnected. [text] is the latest human-readable status. */
    var state = "off"
        private set
    var text = ""
        private set
    val adapter: BluetoothAdapter = ctx.getSystemService(BluetoothManager::class.java).adapter
    var host: BluetoothDevice? = null
        private set
    private var hid: BluetoothHidDevice? = null
    private var buttons = 0
    private val prefs = ctx.getSharedPreferences("hid", Context.MODE_PRIVATE)

    val savedAddress: String? get() = prefs.getString("host", null)

    private fun onState(msg: String, newState: String? = null) {
        if (newState != null) state = newState
        text = msg
        onChange()
    }

    private var registered = false
    private var proxyRequested = false

    /** Safe to call repeatedly (MainActivity calls it on every resume). */
    fun start() {
        startSender()
        if (hid != null) return register()
        if (proxyRequested) return
        proxyRequested = true
        if (!adapter.getProfileProxy(ctx, proxyListener, BluetoothProfile.HID_DEVICE)) {
            proxyRequested = false
            onState("This phone has no Bluetooth HID device support", "off")
        }
    }

    // Android refuses registerApp unless the app is in the foreground ("failed because the app is
    // not foreground" in logcat), e.g. when launched over the lock screen; the next resume retries.
    private fun register() {
        val h = hid ?: return
        if (registered) return
        val sdp = BluetoothHidDeviceAppSdpSettings(
            "Lectern", "Lectern remote", "Lectern",
            BluetoothHidDevice.SUBCLASS1_COMBO, DESCRIPTOR,
        )
        if (!h.registerApp(sdp, null, null, ctx.mainExecutor, callback)) {
            onState("Couldn't register as a Bluetooth mouse. Unlock the phone and reopen Lectern.", "off")
        }
    }

    fun stop() {
        main.removeCallbacks(retry); retries = 0
        hid?.let {
            host?.let { h -> it.disconnect(h) } // tell the Mac first, so it doesn't keep a stale link
            it.unregisterApp()
            adapter.closeProfileProxy(BluetoothProfile.HID_DEVICE, it)
        }
        stopSender()
        hid = null
        host = null
        registered = false
        proxyRequested = false
    }

    // A connect made right after the Mac dropped the old link (or while it is still tearing it
    // down) fails at once; seen after a manual Disconnect on the Mac. Retry a few times with
    // backoff, but only failed attempts: a connection the Mac closes later stays closed, so a
    // Disconnect clicked on the Mac is respected.
    private val main = Handler(Looper.getMainLooper())
    private var retries = 0
    private var attemptNs = 0L
    private val retry = Runnable { savedHost()?.let { connect(it) } }

    fun connect(device: BluetoothDevice) {
        val h = hid ?: return onState("Not ready yet")
        main.removeCallbacks(retry)
        if (host == device) {
            // Tapping the connected Mac = reconnect: the escape hatch for a link that both sides
            // call connected but that delivers nothing (see onAppStatusChanged).
            attemptNs = 0L
            h.disconnect(device)
            host = null
            onState("Reconnecting to ${device.name}…", "connecting")
            main.postDelayed({ connect(device) }, SETTLE_MS)
            return
        }
        host?.let { h.disconnect(it) }
        attemptNs = System.nanoTime()
        onState("Connecting to ${device.name}…", "connecting")
        if (!h.connect(device)) attemptFailed("Could not connect to ${device.name}")
    }

    /** User-facing (re)open: try the saved Mac again if we are registered but idle. */
    fun reconnectIfIdle() {
        if (!registered || state == "connected" || state == "connecting") return
        retries = 0
        savedHost()?.let { connect(it) }
    }

    private fun attemptFailed(msg: String) {
        if (retries < MAX_RETRIES && hid != null && savedHost() != null) {
            retries++
            main.postDelayed(retry, 1500L shl (retries - 1))
            onState("$msg. Retrying…", "connecting")
        } else {
            onState(msg, "disconnected")
        }
    }

    /** Calibration only (android/tools/tick_curve.py): one raw wheel report, bypassing pacing. */
    fun rawWheel(n: Int) = synchronized(lock) { mouse(0, 0, n, 0) }

    // ---- Mac helper (app/PhoneLink.swift in Lectern.app)
    // Vendor report 4 carries pixel scroll / laser / focus to the helper, which posts smooth pixel
    // scrolling and draws the laser dot. Used only while its heartbeat (output report 5, every 1 s)
    // keeps arriving; otherwise everything falls back to plain mouse/keyboard behaviour.
    @Volatile private var helperSeenNs = 0L
    private var helperWas = false
    val helper: Boolean get() = host != null && System.nanoTime() - helperSeenNs < HELPER_TIMEOUT_NS
    private var hsX = 0f // pending helper scroll, quarter pixels
    private var hsY = 0f
    private var hlX = 0f // pending helper laser, quarter points
    private var hlY = 0f
    private val helperExpiry = Runnable { helperChanged() }

    private fun heartbeat() {
        helperSeenNs = System.nanoTime()
        main.post { helperChanged() }
        main.removeCallbacks(helperExpiry)
        main.postDelayed(helperExpiry, HELPER_TIMEOUT_NS / 1_000_000 + 100)
    }

    private fun helperChanged() {
        if (helper != helperWas) { helperWas = helper; onChange() }
    }

    /** Page scroll message in CSS px (natural sign and Scroll speed applied): smooth pixel scroll via
     *  the helper if it runs, else wheel notches (positive wheel = up, so wheel = -dy). */
    fun pageScroll(dx: Float, dy: Float) {
        if (helper) synchronized(lock) { hsX += dx * 4; hsY += dy * 4; lock.notify() }
        else scroll(-dy, dx)
    }

    /** Laser delta in Mac points (page already applied Laser speed). False: no helper, caller moves the pointer. */
    fun helperLaser(dx: Float, dy: Float): Boolean {
        if (!helper) return false
        synchronized(lock) { hlX += dx * 4; hlY += dy * 4; lock.notify() }
        return true
    }

    fun helperLaserHide() = synchronized(lock) {
        if (!helper) return@synchronized
        helperFlushLocked()
        hlX = 0f; hlY = 0f
        vendor(3, 0, 0)
    }

    /** False: no helper, Silence can't be done over Bluetooth alone. */
    fun helperFocus(): Boolean {
        if (!helper) return false
        synchronized(lock) { vendor(4, 0, 0) }
        return true
    }

    /** Send whatever helper scroll/laser is pending (whole quarter units; fractions stay). */
    private fun helperFlushLocked(): Boolean {
        var sent = false
        val sx = hsX.toInt().coerceIn(-32767, 32767); val sy = hsY.toInt().coerceIn(-32767, 32767)
        if (sx != 0 || sy != 0) { hsX -= sx; hsY -= sy; vendor(1, sx, sy); sent = true }
        val lx = hlX.toInt().coerceIn(-32767, 32767); val ly = hlY.toInt().coerceIn(-32767, 32767)
        if (lx != 0 || ly != 0) { hlX -= lx; hlY -= ly; vendor(2, lx, ly); sent = true }
        return sent
    }

    private fun vendor(type: Int, a: Int, b: Int) = send(4, byteArrayOf(
        type.toByte(), a.toByte(), (a shr 8).toByte(), b.toByte(), (b shr 8).toByte(), 0, 0, 0,
    ))

    // ---- pacing
    // The Mac keeps the link in sniff mode (7.5-10 ms interval seen), so a report only leaves at
    // a sniff anchor. Sending one report per touch event (60-120 Hz) beats against that grid and
    // the cursor alternates 10/20 ms steps. Instead, movement goes into a backlog that a sender
    // thread drains on a fixed tick, a fraction per tick, like the Mac-side Pacer. 7.5 ms measured
    // best; 5 ms was erratic while the Mac also streamed A2DP (more packets fight the audio link).
    private val lock = Object()
    private var pendX = 0f
    private var pendY = 0f
    @Volatile var tickNanos = 7_500_000L
    private var sender: Thread? = null

    fun move(dx: Float, dy: Float) = synchronized(lock) {
        pendX += dx; pendY += dy
        lock.notify()
    }

    // ---- scrolling
    // macOS accelerates mouse wheels by notch rate, so "N notches per finger px" felt dead when
    // slow and wild when fast. Measured on Sota's Mac (android/tools/tick_trace.py, 2026-10-09):
    // - a notch more than 150 ms after the previous one scrolls 1 px and resets the Mac's state;
    // - otherwise the Mac keeps an exponential average E of notch spacing (weight 0.24, starting
    //   at 150 ms) and the notch scrolls STEADY_PX(E): ~10 px at 150 ms up to ~94 px at 12 ms.
    // The phone runs the same model per axis, keeps the backlog in Mac pixels, and sends a notch
    // only when the backlog covers at least half of what the Mac will make of it. Output then
    // follows finger travel ~1:1 except at very slow speeds, where macOS has no setting between
    // 1 px notches (<7 px/s) and ~10 px notches (>60 px/s); there the mix averages out.
    private class Axis {
        var pend = 0f
        var lastNs = 0L
        var ema = RESET_MS
        var dir = 0 // sign of the latest finger input

        /** A notch can overshoot the backlog; that debt only offsets later input in the same
         *  direction. It must never turn into notches the other way (the "slides back" bug). */
        fun add(px: Float) {
            if (px == 0f) return
            val d = if (px > 0) 1 else -1
            if (d != dir) { pend = 0f; dir = d }
            pend += px
        }

        /** What the Mac would scroll for a notch sent [now], and the average it would leave. */
        fun predict(now: Long): Pair<Float, Float> {
            val gap = (now - lastNs) / 1e6f
            if (gap > RESET_MS) return 1f to RESET_MS
            val e = ema + EMA_WEIGHT * (gap - ema)
            return steadyPx(e) * MODEL_GAIN to e
        }

        /** -1, 0 or 1 notch this tick; charges the backlog with the predicted Mac pixels. */
        fun step(now: Long): Int {
            if (pend * dir <= 0f) return 0
            val (px, e) = predict(now)
            if (abs(pend) < px * 0.5f) return 0
            val n = dir
            pend -= n * px; lastNs = now; ema = e
            return n
        }
    }

    private val wheel = Axis()
    private val pan = Axis()
    private var lastScrollInNs = 0L

    /** [wheelPx]/[panPx]: wanted Mac scroll in pixels; positive wheel = up/away, positive pan = right. */
    fun scroll(wheelPx: Float, panPx: Float) = synchronized(lock) {
        wheel.add(wheelPx); pan.add(panPx)
        lastScrollInNs = System.nanoTime()
        lock.notify()
    }

    /** Scroll part of a tick: (wheel, pan) notches. */
    private fun scrollStepLocked(now: Long): Pair<Int, Int> {
        if (now - lastScrollInNs > SCROLL_RESIDUE_NS) { wheel.pend = 0f; pan.pend = 0f } // leftovers after a stop
        return wheel.step(now) to pan.step(now)
    }

    /** [mask] is 1 left, 2 right. Pending movement goes out first so order is preserved. */
    fun button(mask: Int, down: Boolean) = synchronized(lock) {
        flushLocked()
        buttons = if (down) buttons or mask else buttons and mask.inv()
        mouse(0, 0, 0, 0)
    }

    fun click(mask: Int) {
        button(mask, true)
        button(mask, false)
    }

    fun releaseAll() = synchronized(lock) {
        if (buttons != 0) { buttons = 0; mouse(0, 0, 0, 0) }
    }

    fun key(usage: Int, modifiers: Int = 0) = synchronized(lock) {
        flushLocked()
        send(1, byteArrayOf(modifiers.toByte(), 0, usage.toByte(), 0, 0, 0, 0, 0))
        send(1, ByteArray(8))
    }

    fun consumer(usage: Int) = synchronized(lock) {
        send(3, byteArrayOf(usage.toByte(), (usage shr 8).toByte()))
        send(3, ByteArray(2))
    }

    private fun startSender() {
        if (sender != null) return
        sender = Thread({
            var next = System.nanoTime()
            try {
                while (true) {
                    synchronized(lock) {
                        while (idleLocked()) { lock.wait(); next = System.nanoTime() }
                        stepLocked()
                    }
                    next += tickNanos
                    val wait = next - System.nanoTime()
                    if (wait > 0) Thread.sleep(wait / 1_000_000, (wait % 1_000_000).toInt())
                    else next = System.nanoTime() // fell behind; don't burst to catch up
                }
            } catch (_: InterruptedException) {
            }
        }, "hid-sender").apply { priority = Thread.MAX_PRIORITY; isDaemon = true; start() }
    }

    private fun stopSender() {
        sender?.interrupt()
        sender = null
    }

    private fun idleLocked() =
        abs(pendX) < 1 && abs(pendY) < 1 && abs(wheel.pend) < 1 && abs(pan.pend) < 1 &&
            abs(hsX) < 1 && abs(hsY) < 1 && abs(hlX) < 1 && abs(hlY) < 1

    /** One tick: send ALPHA of the movement backlog (all of it once it is small), plus due notches. */
    private fun stepLocked() {
        val tx = if (abs(pendX) < 2) pendX else pendX * ALPHA
        val ty = if (abs(pendY) < 2) pendY else pendY * ALPHA
        val ix = tx.toInt()
        val iy = ty.toInt()
        val (w, p) = scrollStepLocked(System.nanoTime())
        helperFlushLocked()
        if (ix == 0 && iy == 0 && w == 0 && p == 0) return
        pendX -= ix; pendY -= iy
        mouse(ix, iy, w, p)
    }

    /** Before a click or key: send all pending pointer movement (scroll keeps its own pacing). */
    private fun flushLocked() {
        val ix = pendX.toInt()
        val iy = pendY.toInt()
        if (ix == 0 && iy == 0) return
        pendX -= ix; pendY -= iy
        mouse(ix, iy, 0, 0)
    }

    private fun mouse(dx: Int, dy: Int, wheel: Int, pan: Int) {
        val x = dx.coerceIn(-32767, 32767)
        val y = dy.coerceIn(-32767, 32767)
        send(2, byteArrayOf(
            buttons.toByte(),
            x.toByte(), (x shr 8).toByte(),
            y.toByte(), (y shr 8).toByte(),
            wheel.coerceIn(-127, 127).toByte(),
            pan.coerceIn(-127, 127).toByte(),
        ))
    }

    private fun send(id: Int, data: ByteArray) {
        val h = hid ?: return
        val d = host ?: return
        h.sendReport(d, id, data)
    }

    private fun savedHost(): BluetoothDevice? {
        val address = prefs.getString("host", null) ?: return null
        return adapter.bondedDevices.firstOrNull { it.address == address }
    }

    private val proxyListener = object : BluetoothProfile.ServiceListener {
        override fun onServiceConnected(profile: Int, proxy: BluetoothProfile) {
            hid = proxy as BluetoothHidDevice
            register()
        }

        override fun onServiceDisconnected(profile: Int) {
            hid = null
            registered = false
            proxyRequested = false
            host = null
            onState("Bluetooth HID service stopped", "off")
        }
    }

    private val callback = object : BluetoothHidDevice.Callback() {
        override fun onAppStatusChanged(pluggedDevice: BluetoothDevice?, registered: Boolean) {
            this@HidPeripheral.registered = registered
            if (!registered) return onState("Not registered as a HID device", "off")
            // Connecting while the Mac is still closing the previous link (app reinstalled or killed
            // a moment ago) gave a link both sides call connected that delivers no input. Let the
            // old link settle first.
            val target = pluggedDevice ?: savedHost()
            if (target != null) {
                onState("Connecting to ${target.name}…", "connecting")
                main.postDelayed({ if (host == null) connect(target) }, SETTLE_MS)
            }
            else onState("", "ready")
        }

        override fun onConnectionStateChanged(device: BluetoothDevice, state: Int) {
            when (state) {
                BluetoothProfile.STATE_CONNECTED -> {
                    host = device
                    retries = 0; main.removeCallbacks(retry)
                    prefs.edit().putString("host", device.address).apply()
                    onState("Connected to ${device.name}", "connected")
                }
                BluetoothProfile.STATE_CONNECTING -> onState("Connecting to ${device.name}…", "connecting")
                BluetoothProfile.STATE_DISCONNECTED -> {
                    if (host != null && host != device) return // an old host dropped; we're on another
                    host = null; buttons = 0
                    if (System.nanoTime() - attemptNs < 5_000_000_000L) attemptFailed("Couldn't connect to ${device.name}")
                    else onState("Disconnected from ${device.name}", "disconnected")
                }
            }
        }

        override fun onGetReport(device: BluetoothDevice, type: Byte, id: Byte, bufferSize: Int) {
            val size = when (id.toInt()) { 1 -> 8; 2 -> 7; 3 -> 2; 4 -> 8; 5 -> 2; else -> 0 }
            if (size == 0) hid?.reportError(device, BluetoothHidDevice.ERROR_RSP_INVALID_RPT_ID)
            else hid?.replyReport(device, type, id, ByteArray(size))
        }

        // Report mode is 1. Boot mode (0) would make the stack drop our report-ID reports, which may be
        // why one early phone-initiated reconnect delivered nothing; log it so it shows up in logcat.
        override fun onSetProtocol(device: BluetoothDevice, protocol: Byte) {
            android.util.Log.i("Lectern", "Mac set protocol $protocol")
        }

        override fun onSetReport(device: BluetoothDevice, type: Byte, id: Byte, data: ByteArray) {
            if (id.toInt() == 5) heartbeat()
            hid?.reportError(device, BluetoothHidDevice.ERROR_RSP_SUCCESS)
        }

        // Output reports may also arrive on the interrupt channel instead of as SET_REPORT.
        override fun onInterruptData(device: BluetoothDevice, reportId: Byte, data: ByteArray) {
            if (reportId.toInt() == 5) heartbeat()
        }
    }

    companion object {
        const val LEFT = 1
        const val RIGHT = 2

        private const val ALPHA = 0.5f
        private const val SCROLL_RESIDUE_NS = 300_000_000L
        private const val MAX_RETRIES = 4
        private const val SETTLE_MS = 1500L
        private const val HELPER_TIMEOUT_NS = 2_500_000_000L

        private const val RESET_MS = 150f
        private const val EMA_WEIGHT = 0.24f
        // Closed-loop check (scroll_curve.py) showed the Mac giving ~15% more than the model above.
        private const val MODEL_GAIN = 1.15f

        /** Mac px per notch for a steady notch spacing (ms), measured with tick_curve.py, smoothed. */
        private val STEADY_PX = listOf(
            12f to 94f, 16f to 92f, 22f to 89f, 30f to 85f, 40f to 78f, 55f to 68f, 70f to 58f,
            85f to 37f, 100f to 25f, 130f to 14f, 150f to 10f,
        )

        private fun steadyPx(ms: Float): Float {
            if (ms <= STEADY_PX[0].first) return STEADY_PX[0].second
            for (i in 1 until STEADY_PX.size) {
                val (m1, p1) = STEADY_PX[i]
                if (ms <= m1) {
                    val (m0, p0) = STEADY_PX[i - 1]
                    return p0 + (p1 - p0) * (ms - m0) / (m1 - m0)
                }
            }
            return STEADY_PX.last().second
        }

        // Keyboard usages (page 0x07)
        const val KEY_B = 0x05
        const val KEY_ENTER = 0x28
        const val KEY_ESC = 0x29
        const val KEY_BACKSPACE = 0x2A
        const val KEY_SPACE = 0x2C
        const val KEY_RIGHT = 0x4F
        const val KEY_LEFT = 0x50
        const val KEY_DOWN = 0x51
        const val KEY_UP = 0x52

        // Consumer usages (page 0x0C)
        const val VOL_UP = 0xE9
        const val VOL_DOWN = 0xEA
        const val MUTE = 0xE2

        private val DESCRIPTOR = intArrayOf(
            // Keyboard, report 1: modifiers, reserved, 6 keys
            0x05, 0x01, 0x09, 0x06, 0xA1, 0x01, 0x85, 0x01,
            0x05, 0x07, 0x19, 0xE0, 0x29, 0xE7, 0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95, 0x08, 0x81, 0x02,
            0x95, 0x01, 0x75, 0x08, 0x81, 0x01,
            0x95, 0x06, 0x75, 0x08, 0x15, 0x00, 0x25, 0x65, 0x05, 0x07, 0x19, 0x00, 0x29, 0x65, 0x81, 0x00,
            0xC0,
            // Mouse, report 2: 3 buttons, X/Y int16, wheel int8, AC Pan int8
            0x05, 0x01, 0x09, 0x02, 0xA1, 0x01, 0x85, 0x02, 0x09, 0x01, 0xA1, 0x00,
            0x05, 0x09, 0x19, 0x01, 0x29, 0x03, 0x15, 0x00, 0x25, 0x01, 0x95, 0x03, 0x75, 0x01, 0x81, 0x02,
            0x95, 0x01, 0x75, 0x05, 0x81, 0x03,
            0x05, 0x01, 0x09, 0x30, 0x09, 0x31, 0x16, 0x01, 0x80, 0x26, 0xFF, 0x7F, 0x75, 0x10, 0x95, 0x02, 0x81, 0x06,
            0x09, 0x38, 0x15, 0x81, 0x25, 0x7F, 0x75, 0x08, 0x95, 0x01, 0x81, 0x06,
            0x05, 0x0C, 0x0A, 0x38, 0x02, 0x15, 0x81, 0x25, 0x7F, 0x75, 0x08, 0x95, 0x01, 0x81, 0x06,
            0xC0, 0xC0,
            // Consumer control, report 3: one 16-bit usage
            0x05, 0x0C, 0x09, 0x01, 0xA1, 0x01, 0x85, 0x03,
            0x15, 0x00, 0x26, 0xFF, 0x03, 0x19, 0x00, 0x2A, 0xFF, 0x03, 0x75, 0x10, 0x95, 0x01, 0x81, 0x00,
            0xC0,
            // Vendor (Lectern helper), report 4 in: 8 bytes; report 5 out: 2-byte heartbeat
            0x06, 0x00, 0xFF, 0x09, 0x01, 0xA1, 0x01,
            0x85, 0x04, 0x09, 0x02, 0x15, 0x00, 0x26, 0xFF, 0x00, 0x75, 0x08, 0x95, 0x08, 0x81, 0x02,
            0x85, 0x05, 0x09, 0x03, 0x75, 0x08, 0x95, 0x02, 0x91, 0x02,
            0xC0,
        ).map { it.toByte() }.toByteArray()
    }
}
