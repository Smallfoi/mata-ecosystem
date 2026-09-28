import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

/// Чьи это локальные данные (аудит C03).
///
/// Телефон — один, аккаунтов на нём может побывать несколько: А вышел, вошёл Б.
/// Всё, что копится локально до отправки (офлайн-очереди) и что показывается
/// из локальной памяти (история забегов), помечается владельцем — id аккаунта,
/// под которым это появилось. Отправляем и показываем только своё: данные А не
/// уходят под токеном Б и не видны Б. Данные А при этом не стираются — дождутся
/// его следующего входа (офлайн-забег на улице не должен теряться).

/// Ключ, под которым сессия хранит id вошедшего аккаунта (см. AuthNotifier).
/// Читаем его напрямую только для разовой миграции старых данных.
const authUserIdPrefsKey = 'kvartal.auth.user_id.v1';

/// Поле владельца в элементе офлайн-очереди. На сервер не уходит.
const ownerField = '_owner';

/// Владелец неизвестен: данные появились до этой версии, а в момент обновления
/// никто не был в приложении. Такие записи НЕ отправляются ни под каким
/// аккаунтом и не показываются — угадать, чьи они, нельзя.
const unknownOwner = '?';

/// Кем помечать новые данные прямо сейчас: id вошедшего, иначе [unknownOwner].
String ownerTag(String? accountId) =>
    (accountId == null || accountId.isEmpty) ? unknownOwner : accountId;

/// Принадлежит ли элемент очереди аккаунту [accountId].
bool isOwnedBy(Map<dynamic, dynamic> item, String? accountId) =>
    accountId != null &&
    accountId.isNotEmpty &&
    item[ownerField]?.toString() == accountId;

/// Копия элемента с владельцем.
Map<String, dynamic> withOwner(Map<dynamic, dynamic> item, String? accountId) =>
    {...Map<String, dynamic>.from(item), ownerField: ownerTag(accountId)};

/// Копия элемента без служебного поля владельца — то, что уходит на сервер.
Map<String, dynamic> withoutOwner(Map<dynamic, dynamic> item) =>
    Map<String, dynamic>.from(item)..remove(ownerField);

/// Очереди, которые хранятся JSON-строкой со списком объектов.
const ownerScopedJsonListQueues = [
  'kvartal.loyalty.pending.v1',
  'kvartal.shoes.pending.v1',
];

/// Очереди, которые хранятся списком строк, каждая — JSON-объект.
const ownerScopedStringListQueues = ['kvartal.capture_queue.v1'];

const _queuesMigratedKey = 'kvartal.owner_scope.queues.v1';

/// Разовая миграция очередей, записанных до появления владельца (C03).
///
/// Запускается при старте приложения, ДО того как кто-то успеет войти: в этот
/// момент ключ [authUserIdPrefsKey] — это тот, кто был в приложении, когда
/// накопились данные (выход стирает этот ключ). Его и назначаем владельцем.
/// Если никого не было — владелец неизвестен ([unknownOwner]): такие элементы
/// держим, но не отправляем под чужим аккаунтом.
Future<void> migrateOwnerlessQueues(SharedPreferences prefs) async {
  if (prefs.getBool(_queuesMigratedKey) == true) return;
  final owner = ownerTag(prefs.getString(authUserIdPrefsKey));

  for (final key in ownerScopedJsonListQueues) {
    final raw = prefs.getString(key);
    if (raw == null || raw.isEmpty) continue;
    try {
      final items = (jsonDecode(raw) as List).whereType<Map>().map(
        (m) => m.containsKey(ownerField)
            ? Map<String, dynamic>.from(m)
            : withOwner(m, owner),
      );
      await prefs.setString(key, jsonEncode(items.toList()));
    } catch (_) {
      // битая очередь — оставляем как есть, чтение её отбросит
    }
  }

  for (final key in ownerScopedStringListQueues) {
    final list = prefs.getStringList(key);
    if (list == null || list.isEmpty) continue;
    final next = <String>[];
    for (final raw in list) {
      try {
        final m = jsonDecode(raw);
        if (m is! Map) continue;
        next.add(
          jsonEncode(m.containsKey(ownerField) ? m : withOwner(m, owner)),
        );
      } catch (_) {
        // битая запись — выбрасываем (так же делает и отправка)
      }
    }
    await prefs.setStringList(key, next);
  }

  await prefs.setBool(_queuesMigratedKey, true);
}
