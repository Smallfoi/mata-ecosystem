import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/core/security/integrity_service.dart';

/// Отпечаток пробежки обязан совпадать с сервером байт в байт, иначе каждый
/// честный токен сервер сочтёт подменой (D-129). Эталоны посчитаны той же
/// формулой в Python (attestation/tests.py → RequestHashTests).
void main() {
  test('совпадает с сервером: метры вниз, время в мс', () {
    expect(
      runRequestHash(
        runId: 'r1',
        distanceMeters: 5000.99,
        elapsedSeconds: 1800,
        finishedAtMs: 1700000000000,
      ),
      '7a312de904576bbfbab3f4bfcb1e1e5b676a955f627629ef530dc7400d525850',
    );
  });

  test('нет времени финиша — пустое место', () {
    expect(
      runRequestHash(runId: 'r1', distanceMeters: 10.4, elapsedSeconds: 5),
      '1a0f4ae65a9e0eea46b74bff741a0270f640cb5421b1c2e11bebabbf5dba6089',
    );
  });

  test('без номера проекта токен не просим — забег уходит как раньше', () async {
    expect(
      await integrityForRun(
        runId: 'r1',
        distanceMeters: 1,
        elapsedSeconds: 1,
      ),
      isNull,
    );
  });
}
