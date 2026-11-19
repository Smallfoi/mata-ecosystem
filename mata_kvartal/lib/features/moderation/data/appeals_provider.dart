import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../auth/data/auth_provider.dart';

/// Обращения в модерацию (§10 готовности): чем кончились мои жалобы и какие
/// меры применили ко мне — с правом один раз возразить.
///
/// Жалоба и мера на сервере разделены намеренно: тот, к кому применили меру,
/// видит только слова модератора, а не жалобу — в ней чужое имя и чужой текст.

class MyReport {
  final String id;
  final String targetName;
  final String reasonTitle;
  final String status; // new | accepted | rejected
  final String statusTitle;
  final DateTime? createdAt;

  const MyReport({
    required this.id,
    required this.targetName,
    required this.reasonTitle,
    required this.status,
    required this.statusTitle,
    this.createdAt,
  });

  factory MyReport.fromJson(Map<String, dynamic> j) => MyReport(
    id: j['id']?.toString() ?? '',
    targetName: j['targetName']?.toString() ?? '—',
    reasonTitle: j['reasonTitle']?.toString() ?? '',
    status: j['status']?.toString() ?? 'new',
    statusTitle: j['statusTitle']?.toString() ?? '',
    createdAt: DateTime.tryParse(j['createdAt']?.toString() ?? ''),
  );
}

class MyMeasure {
  final String id;
  final String kindTitle;
  final String summary;
  final bool active;
  final bool canAppeal;
  final String appealStatus; // none | new | accepted | rejected
  final String appealText;
  final String appealReply;
  final bool aboutClub;
  final DateTime? createdAt;

  const MyMeasure({
    required this.id,
    required this.kindTitle,
    required this.summary,
    this.active = true,
    this.canAppeal = false,
    this.appealStatus = 'none',
    this.appealText = '',
    this.appealReply = '',
    this.aboutClub = false,
    this.createdAt,
  });

  factory MyMeasure.fromJson(Map<String, dynamic> j) => MyMeasure(
    id: j['id']?.toString() ?? '',
    kindTitle: j['kindTitle']?.toString() ?? 'Мера',
    summary: j['summary']?.toString() ?? '',
    active: j['active'] != false,
    canAppeal: j['canAppeal'] == true,
    appealStatus: j['appealStatus']?.toString() ?? 'none',
    appealText: j['appealText']?.toString() ?? '',
    appealReply: j['appealReply']?.toString() ?? '',
    aboutClub: j['targetType'] == 'club',
    createdAt: DateTime.tryParse(j['createdAt']?.toString() ?? ''),
  );
}

final _dio = ApiClient.create();

Options _auth(String token) =>
    Options(headers: {'Authorization': 'Bearer $token'});

final myReportsProvider = FutureProvider.autoDispose<List<MyReport>>((ref) async {
  final token = ref.watch(authProvider).token;
  if (token == null || token.isEmpty) return const [];
  final res = await _dio.get<List<dynamic>>('/me/reports', options: _auth(token));
  return (res.data ?? const [])
      .whereType<Map<String, dynamic>>()
      .map(MyReport.fromJson)
      .toList();
});

final myMeasuresProvider = FutureProvider.autoDispose<List<MyMeasure>>((ref) async {
  final token = ref.watch(authProvider).token;
  if (token == null || token.isEmpty) return const [];
  final res = await _dio.get<List<dynamic>>('/me/measures', options: _auth(token));
  return (res.data ?? const [])
      .whereType<Map<String, dynamic>>()
      .map(MyMeasure.fromJson)
      .toList();
});

class AppealActions {
  AppealActions(this.ref);
  final Ref ref;

  /// Возразить. null — отправлено; иначе текст для человека.
  Future<String?> appeal(String measureId, String text) async {
    final token = ref.read(authProvider).token;
    if (token == null || token.isEmpty) return 'Нужно войти в аккаунт';
    try {
      await _dio.post<dynamic>(
        '/me/measures/$measureId/appeal',
        data: {'text': text},
        options: _auth(token),
      );
      ref.invalidate(myMeasuresProvider);
      return null;
    } on DioException catch (e) {
      final data = e.response?.data;
      return (data is Map ? data['detail']?.toString() : null) ??
          'Нет связи с сервером. Попробуйте ещё раз.';
    }
  }
}

final appealActionsProvider = Provider<AppealActions>(AppealActions.new);
