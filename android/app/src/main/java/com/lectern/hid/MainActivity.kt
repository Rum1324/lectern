package com.lectern.hid

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothClass
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.view.View
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebView
import org.json.JSONArray
import org.json.JSONObject

/**
 * Hosts web/index.html (copied into assets at build time) in a WebView. The page detects
 * window.LecternNative and sends the same JSON messages it would send over the WebSocket;
 * [Bridge] turns them into Bluetooth HID reports.
 */
@SuppressLint("MissingPermission", "SetJavaScriptEnabled")
class MainActivity : Activity() {
    private lateinit var hid: HidPeripheral
    private lateinit var web: WebView
    private var density = 1f
    private var pageReady = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        density = resources.displayMetrics.density
        hid = Lectern.hid(this)
        Lectern.ui = { pushState() }
        intent.getIntExtra("tickUs", 0).takeIf { it > 0 }?.let { hid.tickNanos = it * 1000L } // DEBUG: tuning hook

        if (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0) WebView.setWebContentsDebuggingEnabled(true)
        web = WebView(this).apply {
            setBackgroundColor(Color.parseColor("#0E0E10"))
            overScrollMode = View.OVER_SCROLL_NEVER
            isVerticalScrollBarEnabled = false
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true // settings sheet uses localStorage
            addJavascriptInterface(Bridge(), "LecternNative")
        }
        // Edge-to-edge: the WebView hands the system bar insets to the page as env(safe-area-inset-*),
        // which index.html already pads for (viewport-fit=cover). Don't pad natively as well.
        setContentView(web)
        // A fixed https origin gives the page working localStorage; it never loads anything remote.
        val html = assets.open("index.html").bufferedReader().use { it.readText() }
        web.loadDataWithBaseURL("https://lectern.invalid/", html, "text/html", "utf-8", null)

        val missing = (PERMISSIONS + NOTIFY).filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isEmpty()) startHid() else requestPermissions(missing.toTypedArray(), REQ_PERMS)
    }

    override fun onRequestPermissionsResult(code: Int, perms: Array<out String>, results: IntArray) {
        super.onRequestPermissionsResult(code, perms, results)
        if (PERMISSIONS.all { checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED }) startHid()
        else note("Lectern needs the Nearby devices permission to act as a Bluetooth mouse")
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(code: Int, result: Int, data: Intent?) {
        super.onActivityResult(code, result, data)
        if (code == REQ_ENABLE) {
            if (hid.adapter.isEnabled) { hid.start(); LecternService.start(this) } else note("Bluetooth is off")
        }
    }

    override fun onResume() {
        super.onResume()
        if (PERMISSIONS.all { checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED } && hid.adapter.isEnabled) {
            hid.start()
            hid.reconnectIfIdle()
            LecternService.start(this)
        }
    }

    // The Bluetooth registration lives on in LecternService; only Stop or swiping from Recents ends it.
    override fun onDestroy() {
        Lectern.ui = null
        web.destroy()
        super.onDestroy()
    }

    private fun startHid() {
        if (hid.adapter.isEnabled) { hid.start(); LecternService.start(this) }
        else startActivityForResult(Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE), REQ_ENABLE)
    }

    private fun pushState() {
        if (!pageReady) return
        val devices = JSONArray()
        val bonded = try { hid.adapter.bondedDevices } catch (_: SecurityException) { emptySet() }
        // Only computers (plus the last-used host): the bonded list also holds headphones, cars, watches.
        val shown = bonded.filter {
            it.bluetoothClass?.majorDeviceClass == BluetoothClass.Device.Major.COMPUTER || it.address == hid.savedAddress
        }
        for (d in shown.sortedBy { it.name ?: "" }) {
            devices.put(JSONObject().put("name", d.name ?: d.address).put("addr", d.address))
        }
        val m = JSONObject()
            .put("t", "bt")
            .put("state", hid.state)
            .put("text", hid.text)
            .put("host", hid.host?.name ?: "")
            .put("hostAddr", hid.host?.address ?: hid.savedAddress ?: "")
            .put("saved", hid.savedAddress != null)
            .put("helper", hid.helper)
            .put("devices", devices)
        send(m)
    }

    private fun note(text: String) = send(JSONObject().put("t", "note").put("text", text))

    private fun send(m: JSONObject) {
        runOnUiThread { web.evaluateJavascript("window.lecternRecv && lecternRecv($m)", null) }
    }

    /** Called from the page's JS thread. Movement is thread-safe in HidPeripheral. */
    private inner class Bridge {
        @JavascriptInterface
        fun ready() = runOnUiThread { pageReady = true; pushState() }

        @JavascriptInterface
        fun connect(address: String) = runOnUiThread {
            hid.adapter.bondedDevices.firstOrNull { it.address == address }?.let { hid.connect(it) }
        }

        @JavascriptInterface
        fun discoverable() = runOnUiThread {
            startActivity(Intent(BluetoothAdapter.ACTION_REQUEST_DISCOVERABLE)
                .putExtra(BluetoothAdapter.EXTRA_DISCOVERABLE_DURATION, 120))
        }

        @JavascriptInterface
        fun post(json: String) {
            val m = try { JSONObject(json) } catch (_: Exception) { return }
            val right = m.optString("b") == "right"
            val mask = if (right) HidPeripheral.RIGHT else HidPeripheral.LEFT
            when (m.optString("t")) {
                // Page units are CSS px; the page already applied the pointer/laser speed setting.
                "m" -> hid.move(m.optDouble("dx").toFloat() * density, m.optDouble("dy").toFloat() * density)
                "laser" -> if (m.has("dx")) {
                    val dx = m.optDouble("dx").toFloat(); val dy = m.optDouble("dy").toFloat()
                    if (!hid.helperLaser(dx, dy)) { // no Mac helper: move the pointer instead
                        val k = density / LASER_DEFAULT
                        hid.move(dx * k, dy * k)
                    }
                } else if (m.has("on")) hid.helperLaserHide()
                // Page sends finger travel in CSS px (natural-scroll sign and Scroll speed applied);
                // 1 CSS px -> 1 Mac px, as the server posts it.
                "s" -> hid.pageScroll(m.optDouble("dx").toFloat(), m.optDouble("dy").toFloat())
                "click" -> hid.click(mask)
                "btn" -> hid.button(mask, m.optBoolean("down"))
                "key" -> KEYS[m.optString("k")]?.let { hid.key(it) }
                "vol" -> when (m.optString("a")) {
                    "up" -> hid.consumer(HidPeripheral.VOL_UP)
                    "down" -> hid.consumer(HidPeripheral.VOL_DOWN)
                    "mute" -> hid.consumer(HidPeripheral.MUTE)
                }
                "focus" -> if (!hid.helperFocus()) note("Silence needs Lectern running on the Mac")
                "rawwheel" -> hid.rawWheel(m.optInt("n")) // calibration tool only
            }
        }
    }

    companion object {
        private const val REQ_PERMS = 1
        private const val REQ_ENABLE = 2
        private const val LASER_DEFAULT = 2.6f // page's default laser speed maps to 1 count per px
        private val KEYS = mapOf(
            "left" to HidPeripheral.KEY_LEFT, "right" to HidPeripheral.KEY_RIGHT,
            "up" to HidPeripheral.KEY_UP, "down" to HidPeripheral.KEY_DOWN,
            "b" to HidPeripheral.KEY_B, "esc" to HidPeripheral.KEY_ESC,
            "space" to HidPeripheral.KEY_SPACE, "enter" to HidPeripheral.KEY_ENTER,
            "backspace" to HidPeripheral.KEY_BACKSPACE,
        )
        private val PERMISSIONS = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S)
            listOf(Manifest.permission.BLUETOOTH_CONNECT, Manifest.permission.BLUETOOTH_ADVERTISE)
        else emptyList()
        // Optional: without it the keep-alive notification is hidden, the service still runs.
        private val NOTIFY = if (Build.VERSION.SDK_INT >= 33) listOf(Manifest.permission.POST_NOTIFICATIONS) else emptyList()
    }
}
