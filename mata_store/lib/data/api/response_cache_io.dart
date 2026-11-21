import 'dart:io';

import 'package:path_provider/path_provider.dart';

/// Последние ответы каталога на диске телефона (этап 5 оптимизации, 21.11.2026).
///
/// Файл, а не SharedPreferences: на Android те хранятся одним XML, и запись
/// 300 КБ каталога переписывала бы его целиком при каждом запуске.
class ResponseCache {
  static Directory? _dir;

  static Future<File> _file(String key) async {
    final dir = _dir ??= Directory(
      '${(await getApplicationSupportDirectory()).path}/api_cache',
    );
    if (!await dir.exists()) await dir.create(recursive: true);
    return File('${dir.path}/$key.json');
  }

  static Future<String?> read(String key) async {
    try {
      final f = await _file(key);
      return await f.exists() ? await f.readAsString() : null;
    } catch (_) {
      return null;
    }
  }

  static Future<void> write(String key, String body) async {
    try {
      final f = await _file(key);
      // Пишем во временный и переименовываем: оборванная запись не оставит
      // битый файл, который потом не разберётся.
      final tmp = File('${f.path}.tmp');
      await tmp.writeAsString(body, flush: true);
      await tmp.rename(f.path);
    } catch (_) {}
  }
}
