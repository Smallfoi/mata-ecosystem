import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform;

import 'package:crypto/crypto.dart';
import 'package:flutter/services.dart';

/// Проверка подлинности приложения (D-129), режим «наблюдение».
///
/// Перед отправкой пробежки просим у Google Play токен, в который вшит
/// отпечаток запроса ([runRequestHash]). Сервер отдаёт токен Google и узнаёт:
/// запрос пришёл из нашего приложения и с настоящего телефона. Баллы от этого
/// пока не зависят — это сигнал модератору.
///
/// Тихо без токена (забег уходит как раньше), если: не задан номер облачного
/// проекта (`--dart-define=PLAY_INTEGRITY_PROJECT=...`), Google Play недоступен,
/// ответ не пришёл за [_timeout], или это iOS (App Attest — когда будет
/// аккаунт Apple Developer).
const _projectNumber = String.fromEnvironment('PLAY_INTEGRITY_PROJECT');
const _channel = MethodChannel('kvartal/integrity');
const _timeout = Duration(seconds: 6);

/// Отпечаток пробежки. ДОЛЖЕН совпадать с сервером
/// (backend/django_api/attestation/service.py → run_request_hash):
/// метры — целые вниз, нет времени финиша — пустое место.
String runRequestHash({
  required String runId,
  required double distanceMeters,
  required int elapsedSeconds,
  int? finishedAtMs,
}) {
  final raw = 'mata-run-v1|$runId|${distanceMeters.floor()}|$elapsedSeconds|'
      '${finishedAtMs ?? ''}';
  return sha256.convert(utf8.encode(raw)).toString();
}

/// Поле `integrity` для POST /v1/runs или null — тогда поле не шлём.
Future<Map<String, String>?> integrityForRun({
  required String runId,
  required double distanceMeters,
  required int elapsedSeconds,
  int? finishedAtMs,
}) async {
  try {
    if (Platform.isIOS) return const {'platform': 'ios'};
    if (!Platform.isAndroid || _projectNumber.isEmpty) return null;
    final token = await _channel.invokeMethod<String>('requestToken', {
      'cloudProjectNumber': _projectNumber,
      'requestHash': runRequestHash(
        runId: runId,
        distanceMeters: distanceMeters,
        elapsedSeconds: elapsedSeconds,
        finishedAtMs: finishedAtMs,
      ),
    }).timeout(_timeout);
    if (token == null || token.isEmpty) return null;
    return {'platform': 'android', 'token': token};
  } catch (_) {
    // Нет Google Play, нет сети, старый телефон — забег важнее проверки.
    return null;
  }
}
