package ru.mata.kvartal

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.Bundle
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.roundToLong
import kotlin.math.sin
import kotlin.math.sqrt

class KvartalLocationService : Service(), LocationListener {
    private lateinit var locationManager: LocationManager
    private lateinit var prefs: SharedPreferences
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onCreate() {
        super.onCreate()
        locationManager = getSystemService(Context.LOCATION_SERVICE) as LocationManager
        prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                stopTracking()
                stopSelf()
                return START_NOT_STICKY
            }
            else -> {
                startInForeground()
                acquireWakeLock()
                startTracking()
                return START_STICKY
            }
        }
    }

    override fun onDestroy() {
        stopTracking()
        releaseWakeLock()
        super.onDestroy()
    }

    /// На Android 10+ указываем тип FGS явно — иначе на 14+ запуск может отклониться.
    private fun startInForeground() {
        val notification = buildNotification()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION,
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    /// Partial wake-lock: держим CPU, чтобы GPS писался при выключенном экране.
    private fun acquireWakeLock() {
        if (wakeLock?.isHeld == true) return
        try {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = pm.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK,
                "kvartal:gps_tracking",
            ).apply {
                setReferenceCounted(false)
                acquire(MAX_WAKELOCK_MS)
            }
        } catch (_: Exception) {
            // Wake-lock — best-effort; без него фон менее надёжен, но сервис всё равно работает.
        }
    }

    private fun releaseWakeLock() {
        try {
            if (wakeLock?.isHeld == true) wakeLock?.release()
        } catch (_: Exception) {
            // already released
        }
        wakeLock = null
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun startTracking() {
        if (!hasLocationPermission()) return
        try {
            locationManager.requestLocationUpdates(
                LocationManager.GPS_PROVIDER,
                1000L,
                MIN_PROVIDER_DISTANCE_METERS,
                this,
            )
        } catch (_: Exception) {
            // GPS provider may be unavailable indoors; network provider below is a fallback.
        }
        // Do not append NETWORK_PROVIDER points to the run route: they are often
        // coarse indoors and create star-shaped territory artifacts.
    }

    private fun stopTracking() {
        try {
            locationManager.removeUpdates(this)
        } catch (_: Exception) {
            // Service is already stopped or provider is unavailable.
        }
    }

    override fun onLocationChanged(location: Location) {
        if (location.hasAccuracy() && location.accuracy > MAX_ACCEPTED_ACCURACY_METERS) return
        if (location.speed > MAX_RUN_SPEED_MS) return
        appendPoint(location)
    }

    @Deprecated("Deprecated in Java")
    override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) = Unit

    override fun onProviderEnabled(provider: String) = Unit

    override fun onProviderDisabled(provider: String) = Unit

    private fun appendPoint(location: Location) {
        val raw = prefs.getString(ACTIVE_RUN_KEY, null) ?: return
        val now = System.currentTimeMillis()
        val data = try {
            JSONObject(raw)
        } catch (_: Exception) {
            return
        }

        if (data.optString("status") != "active") return

        val route = data.optJSONArray("route") ?: JSONArray()
        val lat = location.latitude
        val lng = location.longitude
        var distanceMeters = data.optDouble("distanceMeters", 0.0)

        if (route.length() > 0) {
            val last = route.optJSONArray(route.length() - 1) ?: return
            val lastLat = last.optDouble(0)
            val lastLng = last.optDouble(1)
            val gap = distanceMeters(lastLat, lastLng, lat, lng)
            if (gap < MIN_POINT_DISTANCE_METERS) return
            if (gap > MAX_POINT_GAP_METERS) return
            distanceMeters += gap
        }

        route.put(JSONArray().put(lat).put(lng))
        val previousSavedAt = data.optLong("savedAtMs", now)
        val previousElapsed = data.optLong("elapsedSeconds", 0L)
        val elapsedDelta = ((now - previousSavedAt).coerceAtLeast(0L) / 1000.0).roundToLong()

        data.put("schemaVersion", ACTIVE_RUN_SCHEMA_VERSION)
        data.put("status", "active")
        data.put("route", route)
        data.put("distanceMeters", distanceMeters)
        data.put("elapsedSeconds", previousElapsed + elapsedDelta)
        data.put("savedAtMs", now)

        prefs.edit().putString(ACTIVE_RUN_KEY, data.toString()).apply()
    }

    private fun hasLocationPermission(): Boolean {
        val fine = ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
        val coarse = ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION)
        return fine == PackageManager.PERMISSION_GRANTED || coarse == PackageManager.PERMISSION_GRANTED
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            "КВАРТАЛ GPS",
            NotificationManager.IMPORTANCE_LOW,
        )
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(channel)
    }

    private fun buildNotification(): Notification {
        val icon = applicationInfo.icon
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(icon)
            .setContentTitle("КВАРТАЛ записывает пробежку")
            .setContentText("GPS активен. Маршрут сохраняется в фоне.")
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    private fun distanceMeters(lat1: Double, lng1: Double, lat2: Double, lng2: Double): Double {
        val earth = 6371000.0
        val dLat = Math.toRadians(lat2 - lat1)
        val dLng = Math.toRadians(lng2 - lng1)
        val rLat1 = Math.toRadians(lat1)
        val rLat2 = Math.toRadians(lat2)
        val a = sin(dLat / 2).pow(2.0) + cos(rLat1) * cos(rLat2) * sin(dLng / 2).pow(2.0)
        return 2 * earth * asin(sqrt(a))
    }

    companion object {
        const val ACTION_START = "ru.mata.kvartal.location.START"
        const val ACTION_STOP = "ru.mata.kvartal.location.STOP"
        private const val CHANNEL_ID = "kvartal_location_tracking"
        private const val NOTIFICATION_ID = 4271
        private const val PREFS_NAME = "FlutterSharedPreferences"
        private const val ACTIVE_RUN_KEY = "flutter.kvartal.active_run.v1"
        private const val ACTIVE_RUN_SCHEMA_VERSION = 2
        private const val MAX_RUN_SPEED_MS = 11.1
        private const val MIN_POINT_DISTANCE_METERS = 2.0
        private const val MAX_POINT_GAP_METERS = 80.0
        // Жёстче по точности + фильтр дистанции на уровне провайдера — убираем дрожь 2–3 м.
        private const val MAX_ACCEPTED_ACCURACY_METERS = 35f
        private const val MIN_PROVIDER_DISTANCE_METERS = 5f
        // Предохранитель: авто-снятие wake-lock через 6 ч (на случай зависшего сервиса).
        private const val MAX_WAKELOCK_MS = 6L * 60 * 60 * 1000
    }
}
