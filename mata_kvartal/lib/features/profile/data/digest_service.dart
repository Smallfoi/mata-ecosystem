import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_config.dart';
import '../../auth/data/auth_provider.dart';
import '../../races/data/race_reminders.dart';

/// Еженедельный дайджест (Квартал 2.0, Ф7 — утверждено 31.08.2026).
///
/// Сервер отдаёт итоги недели (GET /me/digest), приложение планирует локальное
/// уведомление на воскресенье 20:00 с живыми цифрами. Настоящий пуш с сервера
/// подключится вместе с FCM-аккаунтом владельца — текст останется тем же.
class WeekDigest {
  final double weekKm;
  final int weekRuns;
  final int earnedPoints;
  final int territoriesCount;
  final int expiringSoon;

  const WeekDigest({
    this.weekKm = 0,
    this.weekRuns = 0,
    this.earnedPoints = 0,
    this.territoriesCount = 0,
    this.expiringSoon = 0,
  });
}

final _digestDio = Dio(
  BaseOptions(
    baseUrl: ApiConfig.baseUrl,
    connectTimeout: ApiConfig.connectTimeout,
    receiveTimeout: ApiConfig.receiveTimeout,
    headers: {'Content-Type': 'application/json', 'Connection': 'close'},
  ),
);

final weekDigestProvider = FutureProvider.autoDispose<WeekDigest?>((ref) async {
  final token = ref.watch(authProvider).token;
  if (token == null || token.isEmpty) return null;
  final res = await _digestDio.get<Map<String, dynamic>>(
    '/me/digest',
    options: Options(headers: {'Authorization': 'Bearer $token'}),
  );
  final data = res.data ?? {};
  final terr = (data['territories'] as Map<String, dynamic>?) ?? const {};
  final digest = WeekDigest(
    weekKm: (data['weekKm'] as num?)?.toDouble() ?? 0,
    weekRuns: (data['weekRuns'] as num?)?.toInt() ?? 0,
    earnedPoints: (data['earnedPoints'] as num?)?.toInt() ?? 0,
    territoriesCount: (terr['count'] as num?)?.toInt() ?? 0,
    expiringSoon: ((terr['expiringSoon'] as List?) ?? const []).length,
  );
  // Перепланировать воскресное уведомление свежими цифрами — идемпотентно.
  await DigestReminder.schedule(digest);
  return digest;
});

class DigestReminder {
  DigestReminder._();

  static const _id = 0x0DD1;

  /// Ближайшее воскресенье 20:00 (если сегодня воскресенье и 20:00 прошло —
  /// следующее).
  static DateTime nextSunday20([DateTime? now]) {
    now = now ?? DateTime.now();
    var day = DateTime(now.year, now.month, now.day, 20);
    while (day.weekday != DateTime.sunday || !day.isAfter(now)) {
      day = day.add(const Duration(days: 1));
      day = DateTime(day.year, day.month, day.day, 20);
    }
    return day;
  }

  static Future<void> schedule(WeekDigest d) async {
    try {
      final title = d.weekRuns > 0
          ? 'Неделя: ${d.weekKm.toStringAsFixed(1)} км · +${d.earnedPoints} баллов'
          : 'Неделя закрывается — успей пробежать';
      final body = [
        if (d.weekRuns > 0)
          '${d.weekRuns} пробеж${_runsTail(d.weekRuns)} за неделю',
        if (d.territoriesCount > 0) 'кварталов: ${d.territoriesCount}',
        if (d.expiringSoon > 0)
          '${d.expiringSoon} истекает — обнови бегом',
        if (d.weekRuns == 0) 'Один круг — и неделя в серии',
      ].join(' · ');
      await RaceReminders.scheduleAt(
        id: _id,
        title: title,
        body: body,
        when: nextSunday20(),
      );
    } catch (e) {
      debugPrint('DigestReminder.schedule failed: $e');
    }
  }

  static String _runsTail(int n) {
    final mod100 = n % 100;
    if (mod100 >= 11 && mod100 <= 14) return 'ек';
    return switch (n % 10) {
      1 => 'ка',
      2 || 3 || 4 => 'ки',
      _ => 'ек',
    };
  }
}
