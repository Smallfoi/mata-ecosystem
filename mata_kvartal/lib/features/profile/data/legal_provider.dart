import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';

/// Правовой документ экосистемы МАТА (соглашение, политика, согласие, оферта,
/// правила баллов/сообщества). Единый источник правды — backend: документы
/// редактируются в админ-панели, приложение всегда показывает актуальную
/// опубликованную версию (`GET /v1/legal/documents`). JSON парсим защитно.
class LegalDoc {
  final String type;
  final String title;
  final String version;
  final String body;
  final bool required;

  /// Принят ли пользователем (только при запросе с токеном; иначе null).
  final bool? accepted;

  const LegalDoc({
    required this.type,
    required this.title,
    required this.version,
    required this.body,
    required this.required,
    this.accepted,
  });

  factory LegalDoc.fromJson(Map<String, dynamic> j) => LegalDoc(
        type: j['type']?.toString() ?? '',
        title: j['title']?.toString() ?? 'Документ',
        version: j['version']?.toString() ?? '',
        body: j['body']?.toString() ?? '',
        required: j['required'] == true,
        accepted: j['accepted'] is bool ? j['accepted'] as bool : null,
      );
}

final _legalDio = ApiClient.create(headers: {'Content-Type': 'application/json', 'Connection': 'close'});

/// Загрузить опубликованные документы. С токеном — у каждого проставлен
/// `accepted` (принят ли пользователем); без токена — `accepted == null`.
Future<List<LegalDoc>> fetchLegalDocs({String? token}) async {
  final res = await _legalDio.get<List<dynamic>>(
    '/legal/documents',
    options: token == null
        ? null
        : Options(headers: {'Authorization': 'Bearer $token'}),
  );
  return (res.data ?? const [])
      .whereType<Map<String, dynamic>>()
      .map(LegalDoc.fromJson)
      .toList();
}

/// Зафиксировать согласие с текущими опубликованными версиями (по типам).
/// Сервер пишет кто/когда/какую версию принял (аудит согласий, 152-ФЗ).
Future<void> acceptLegalDocs({
  required String token,
  required List<String> types,
  required String source,
}) async {
  await _legalDio.post<dynamic>(
    '/legal/consent',
    data: {'accept': types, 'source': source},
    options: Options(headers: {'Authorization': 'Bearer $token'}),
  );
}

/// Обязательные документы, которые пользователь ещё НЕ принял (нужен токен).
List<LegalDoc> pendingRequired(List<LegalDoc> docs) =>
    docs.where((d) => d.required && d.accepted == false).toList();

/// Опубликованные правовые документы (публичный эндпоинт — токен не нужен).
/// Меняешь текст в админке → приложение подтягивает новый при следующем открытии.
final legalDocumentsProvider =
    FutureProvider.autoDispose<List<LegalDoc>>((ref) => fetchLegalDocs());
