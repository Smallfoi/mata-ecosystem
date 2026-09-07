import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:timezone/data/latest_all.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

import 'races_provider.dart';

/// Локальные напоминания о забегах из «Моих стартов». Только device-local
/// (flutter_local_notifications), без пушей/FCM. Планируем два напоминания:
/// за 7 дней до старта и утром в день старта. При снятии отметки — отменяем.
///
/// Каналы уведомлений и точность: используем НЕточное расписание
/// (inexactAllowWhileIdle) — не требует разрешения SCHEDULE_EXACT_ALARM.
class RaceReminders {
  RaceReminders._();

  static final FlutterLocalNotificationsPlugin _plugin =
      FlutterLocalNotificationsPlugin();
  static bool _inited = false;

  static const _channelId = 'races_reminders';
  static const _channelName = 'Напоминания о стартах';
  static const _channelDesc = 'Напоминания о забегах из «Моих стартов»';

  /// Инициализация плагина + таймзон. Безопасно звать несколько раз.
  static Future<void> init() async {
    if (_inited) return;
    try {
      tzdata.initializeTimeZones();
      const android = AndroidInitializationSettings('@mipmap/ic_launcher');
      const settings = InitializationSettings(android: android);
      await _plugin.initialize(settings);
      _inited = true;
    } catch (e) {
      // Напоминания — не критичны: не роняем приложение из-за них.
      debugPrint('RaceReminders.init failed: $e');
    }
  }

  /// Спросить разрешение на уведомления (Android 13+). Возвращает true, если можно слать.
  static Future<bool> requestPermission() async {
    await init();
    try {
      final android = _plugin.resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin>();
      final granted = await android?.requestNotificationsPermission();
      return granted ?? true;
    } catch (e) {
      debugPrint('RaceReminders.requestPermission failed: $e');
      return false;
    }
  }

  // Стабильные id уведомлений для забега (два напоминания): raceId*2 и raceId*2+1.
  static int _idWeekBefore(int raceId) => (raceId * 2) & 0x7fffffff;
  static int _idDayOf(int raceId) => (raceId * 2 + 1) & 0x7fffffff;

  /// Запланировать напоминания для забега (если дата в будущем).
  static Future<void> scheduleForRace(RaceEvent race) async {
    await init();
    if (!_inited) return;
    final date = race.date;
    if (date == null) return;

    final now = DateTime.now();
    // За 7 дней до старта, в 10:00.
    final weekBefore = DateTime(date.year, date.month, date.day, 10)
        .subtract(const Duration(days: 7));
    // Утром в день старта, в 08:00.
    final dayOf = DateTime(date.year, date.month, date.day, 8);

    if (weekBefore.isAfter(now)) {
      await _zoned(
        _idWeekBefore(race.id),
        'Через неделю — ${race.title}',
        _placeLine(race),
        weekBefore,
      );
    }
    if (dayOf.isAfter(now)) {
      await _zoned(
        _idDayOf(race.id),
        'Сегодня старт — ${race.title}',
        _placeLine(race),
        dayOf,
      );
    }
  }

  /// Отменить напоминания забега.
  static Future<void> cancelForRace(int raceId) async {
    await init();
    if (!_inited) return;
    try {
      await _plugin.cancel(_idWeekBefore(raceId));
      await _plugin.cancel(_idDayOf(raceId));
    } catch (e) {
      debugPrint('RaceReminders.cancelForRace failed: $e');
    }
  }

  static String _placeLine(RaceEvent race) {
    final parts = [race.city, race.place].where((s) => s.isNotEmpty).toList();
    return parts.isEmpty ? 'Не пропусти старт' : parts.join(' · ');
  }

  /// Публичное разовое планирование (дайджест недели и т.п.): отменяет
  /// прежнее уведомление с тем же id и ставит новое.
  static Future<void> scheduleAt({
    required int id,
    required String title,
    required String body,
    required DateTime when,
  }) async {
    await init();
    if (!_inited || !when.isAfter(DateTime.now())) return;
    try {
      await _plugin.cancel(id);
    } catch (_) {}
    await _zoned(id, title, body, when);
  }

  static Future<void> _zoned(
      int id, String title, String body, DateTime when) async {
    try {
      const details = NotificationDetails(
        android: AndroidNotificationDetails(
          _channelId,
          _channelName,
          channelDescription: _channelDesc,
          importance: Importance.high,
          priority: Priority.high,
        ),
      );
      await _plugin.zonedSchedule(
        id,
        title,
        body,
        tz.TZDateTime.from(when, tz.local),
        details,
        androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
        uiLocalNotificationDateInterpretation:
            UILocalNotificationDateInterpretation.absoluteTime,
      );
    } catch (e) {
      debugPrint('RaceReminders._zoned failed: $e');
    }
  }
}
