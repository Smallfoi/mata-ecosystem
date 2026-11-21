/// Веб-сборка (превью Конструктора): каталог всегда свежий, кэша на диске нет.
class ResponseCache {
  static Future<String?> read(String key) async => null;
  static Future<void> write(String key, String body) async {}
}
