package ru.mata.kvartal

import android.content.Intent
import android.os.Build
import io.flutter.embedding.android.FlutterFragmentActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

// FlutterFragmentActivity, а не FlutterActivity: плагин health спрашивает разрешения
// Health Connect через ActivityResultContract, а тот живёт только во фрагментной
// активности. С обычной FlutterActivity диалог разрешений просто не открывается.
class MainActivity : FlutterFragmentActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL).setMethodCallHandler { call, result ->
            when (call.method) {
                "startLocationService" -> {
                    startLocationService()
                    result.success(true)
                }
                "stopLocationService" -> {
                    stopLocationService()
                    result.success(true)
                }
                "getManufacturer" -> {
                    result.success(android.os.Build.MANUFACTURER ?: "")
                }
                else -> result.notImplemented()
            }
        }
        // Шаринг в сторис Инстаграма (нативный интент, как у Стравы):
        // стикер ложится ПОВЕРХ фона, который бегун выбирает сам; карточка —
        // фоном целиком. Без Meta App ID Инстаграм интент игнорирует, поэтому
        // Dart сначала проверяет appId и честно уходит в системный шит.
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, INSTA_CHANNEL).setMethodCallHandler { call, result ->
            when (call.method) {
                "shareSticker" -> result.success(shareToInstagramStory(
                    call.argument("path"), call.argument("appId") ?: "", sticker = true))
                "shareBackground" -> result.success(shareToInstagramStory(
                    call.argument("path"), call.argument("appId") ?: "", sticker = false))
                // «Как у Стравы»: прозрачный стикер уходит в галерею, оттуда его
                // кладут штатным фото-стикером на любое фото и видео — редактор
                // Инсты не ограничивает такие слои, в отличие от интерактивных.
                "saveToGallery" -> {
                    val path = call.argument<String>("path")
                    when {
                        path == null -> result.success(false)
                        Build.VERSION.SDK_INT >= 29 || hasLegacyWritePermission() ->
                            result.success(saveImageToGallery(path))
                        else -> {
                            // Android 8–9: MediaStore пишет только с разрешением
                            // на хранилище — спрашиваем и досылаем ответ позже.
                            pendingGallerySave = path to result
                            androidx.core.app.ActivityCompat.requestPermissions(
                                this,
                                arrayOf(android.Manifest.permission.WRITE_EXTERNAL_STORAGE),
                                REQ_SAVE_GALLERY,
                            )
                        }
                    }
                }
                else -> result.notImplemented()
            }
        }
    }

    private var pendingGallerySave: Pair<String, MethodChannel.Result>? = null

    private fun hasLegacyWritePermission(): Boolean =
        checkSelfPermission(android.Manifest.permission.WRITE_EXTERNAL_STORAGE) ==
            android.content.pm.PackageManager.PERMISSION_GRANTED

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != REQ_SAVE_GALLERY) return
        val (path, pending) = pendingGallerySave ?: return
        pendingGallerySave = null
        val granted = grantResults.isNotEmpty() &&
            grantResults[0] == android.content.pm.PackageManager.PERMISSION_GRANTED
        pending.success(granted && saveImageToGallery(path))
    }

    private fun saveImageToGallery(path: String): Boolean {
        val src = java.io.File(path)
        if (!src.exists()) return false
        return try {
            val values = android.content.ContentValues().apply {
                put(android.provider.MediaStore.Images.Media.DISPLAY_NAME,
                    "KVARTAL_${System.currentTimeMillis()}.png")
                put(android.provider.MediaStore.Images.Media.MIME_TYPE, "image/png")
                if (Build.VERSION.SDK_INT >= 29) {
                    // Своя папка и IS_PENDING (галерея не видит недописанный файл)
                    // доступны только с Android 10; на 8–9 файл ляжет в Pictures.
                    put(android.provider.MediaStore.Images.Media.RELATIVE_PATH,
                        "Pictures/KVARTAL")
                    put(android.provider.MediaStore.Images.Media.IS_PENDING, 1)
                }
            }
            val resolver = contentResolver
            val uri = resolver.insert(
                android.provider.MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
                ?: return false
            resolver.openOutputStream(uri)?.use { out ->
                src.inputStream().use { it.copyTo(out) }
            } ?: return false
            if (Build.VERSION.SDK_INT >= 29) {
                values.clear()
                values.put(android.provider.MediaStore.Images.Media.IS_PENDING, 0)
                resolver.update(uri, values, null, null)
            }
            true
        } catch (_: Exception) {
            false
        }
    }

    private fun shareToInstagramStory(path: String?, appId: String, sticker: Boolean): Boolean {
        if (path == null || appId.isEmpty()) return false
        val file = java.io.File(path)
        if (!file.exists()) return false
        val uri = androidx.core.content.FileProvider.getUriForFile(
            this, "$packageName.instashare", file)
        val intent = Intent("com.instagram.share.ADD_TO_STORY").apply {
            // Явный адресат надёжнее неявного выборщика: уходит именно в Инсту.
            setPackage("com.instagram.android")
            putExtra("source_application", appId)
            putExtra("com.facebook.platform.extra.APPLICATION_ID", appId)
            if (sticker) {
                type = "image/*"
                putExtra("interactive_asset_uri", uri)
                // Градиент подложки по умолчанию — графит Квартала.
                putExtra("top_background_color", "#20252B")
                putExtra("bottom_background_color", "#0F1216")
            } else {
                setDataAndType(uri, "image/*")
            }
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        grantUriPermission("com.instagram.android", uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
        // Не resolveActivity: на части прошивок он возвращает null даже при
        // объявленной видимости — честнее просто запустить и поймать отказ.
        return try {
            startActivity(intent)
            true
        } catch (_: android.content.ActivityNotFoundException) {
            false
        }
    }

    private fun startLocationService() {
        val intent = Intent(this, KvartalLocationService::class.java).apply {
            action = KvartalLocationService.ACTION_START
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
    }

    private fun stopLocationService() {
        val intent = Intent(this, KvartalLocationService::class.java).apply {
            action = KvartalLocationService.ACTION_STOP
        }
        startService(intent)
    }

    companion object {
        private const val CHANNEL = "kvartal/location_service"
        private const val INSTA_CHANNEL = "kvartal/instagram_share"
        private const val REQ_SAVE_GALLERY = 7401
    }
}
