package com.lectern.hid

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder

/**
 * One HidPeripheral per process, so the Bluetooth registration outlives the Activity
 * (back button, rotation, switching apps). [ui] is the visible Activity's listener, if any.
 */
object Lectern {
    private var hid: HidPeripheral? = null
    var ui: (() -> Unit)? = null

    fun hid(ctx: Context): HidPeripheral = hid ?: HidPeripheral(ctx.applicationContext) {
        ui?.invoke()
        LecternService.refresh(ctx.applicationContext)
    }.also { hid = it }
}

/**
 * Foreground service with a persistent notification while Lectern is active. Without it,
 * Xiaomi's Android freezes or kills the app soon after you switch away, the Bluetooth stack never
 * tells the Mac the mouse left, and the Mac then refuses every reconnect ("A connection to … already
 * exists" in its log) until it is disconnected by hand. Swiping Lectern out of Recents or tapping
 * Stop unregisters cleanly.
 */
class LecternService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            Lectern.hid(this).stop()
            running = false
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
            return START_NOT_STICKY
        }
        running = true
        startForeground(ID, build(this), ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        return START_NOT_STICKY
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        Lectern.hid(this).stop()
        running = false
        stopSelf()
    }

    companion object {
        private const val ID = 1
        private const val CHANNEL = "connection"
        private const val ACTION_STOP = "com.lectern.hid.STOP"
        @Volatile private var running = false

        /** From the visible Activity only: Android allows starting a foreground service from there. */
        fun start(ctx: Context) {
            if (!running) ctx.startForegroundService(Intent(ctx, LecternService::class.java))
        }

        fun refresh(ctx: Context) {
            if (running) ctx.getSystemService(NotificationManager::class.java).notify(ID, build(ctx))
        }

        private fun build(ctx: Context): Notification {
            val nm = ctx.getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(NotificationChannel(CHANNEL, "Connection", NotificationManager.IMPORTANCE_LOW))
            val hid = Lectern.hid(ctx)
            val text = when (hid.state) {
                "connected" -> "Connected to ${hid.host?.name ?: "your Mac"}"
                "connecting" -> "Connecting…"
                else -> "Not connected"
            }
            val open = PendingIntent.getActivity(ctx, 0, Intent(ctx, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP), PendingIntent.FLAG_IMMUTABLE)
            val stop = PendingIntent.getService(ctx, 1, Intent(ctx, LecternService::class.java)
                .setAction(ACTION_STOP), PendingIntent.FLAG_IMMUTABLE)
            return Notification.Builder(ctx, CHANNEL)
                .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
                .setContentTitle("Lectern")
                .setContentText(text)
                .setContentIntent(open)
                .setOngoing(true)
                .addAction(Notification.Action.Builder(null, "Stop", stop).build())
                .build()
        }
    }
}
