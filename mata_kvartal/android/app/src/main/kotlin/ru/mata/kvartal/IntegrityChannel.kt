package ru.mata.kvartal

import android.content.Context
import com.google.android.play.core.integrity.IntegrityManagerFactory
import com.google.android.play.core.integrity.StandardIntegrityManager.PrepareIntegrityTokenRequest
import com.google.android.play.core.integrity.StandardIntegrityManager.StandardIntegrityTokenProvider
import com.google.android.play.core.integrity.StandardIntegrityManager.StandardIntegrityTokenRequest
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodChannel

/**
 * Play Integrity (стандартные запросы) для проверки подлинности (D-129).
 *
 * Официальная библиотека Google `com.google.android.play:integrity`: подготовка
 * провайдера (прогрев) делается один раз, дальше каждый токен — быстрый запрос
 * с отпечатком конкретной пробежки. Любая ошибка возвращается в Dart как ошибка,
 * а Dart тихо отправляет забег без токена.
 */
class IntegrityChannel(private val context: Context) {
    private var provider: StandardIntegrityTokenProvider? = null
    private var providerProject: Long = 0

    fun register(messenger: BinaryMessenger) {
        MethodChannel(messenger, CHANNEL).setMethodCallHandler { call, result ->
            if (call.method != "requestToken") {
                result.notImplemented()
                return@setMethodCallHandler
            }
            val project = call.argument<String>("cloudProjectNumber")?.toLongOrNull()
            val hash = call.argument<String>("requestHash")
            if (project == null || hash.isNullOrEmpty()) {
                result.error("bad_args", "нет номера проекта или отпечатка", null)
                return@setMethodCallHandler
            }
            withProvider(project, { p ->
                p.request(StandardIntegrityTokenRequest.builder().setRequestHash(hash).build())
                    .addOnSuccessListener { token -> result.success(token.token()) }
                    .addOnFailureListener { e ->
                        // Провайдер мог устареть — в следующий раз подготовим заново.
                        provider = null
                        result.error("request_failed", e.message, null)
                    }
            }, { e -> result.error("prepare_failed", e.message, null) })
        }
    }

    private fun withProvider(
        project: Long,
        onReady: (StandardIntegrityTokenProvider) -> Unit,
        onError: (Exception) -> Unit,
    ) {
        val cached = provider
        if (cached != null && providerProject == project) {
            onReady(cached)
            return
        }
        IntegrityManagerFactory.createStandard(context.applicationContext)
            .prepareIntegrityToken(
                PrepareIntegrityTokenRequest.builder().setCloudProjectNumber(project).build(),
            )
            .addOnSuccessListener { p ->
                provider = p
                providerProject = project
                onReady(p)
            }
            .addOnFailureListener { e -> onError(e) }
    }

    companion object {
        private const val CHANNEL = "kvartal/integrity"
    }
}
