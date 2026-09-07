import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/features/medals/presentation/medal_widgets.dart';

/// Правило наложений для гравировки реверса: любая подпись после фита
/// обязана помещаться в отведённую ширину (реальный баг: «Личное время
/// на 5 км» вылезало за рамку штампа).
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  double widthOf(String text, TextStyle style) {
    final tp = TextPainter(
      text: TextSpan(text: text, style: style),
      textDirection: TextDirection.ltr,
    )..layout();
    return tp.width;
  }

  test('длинные подписи ужимаются в отведённую ширину', () {
    const base = TextStyle(fontSize: 8, letterSpacing: 2.2, fontWeight: FontWeight.w700);
    const maxW = 104.0; // 52 единицы × s=2
    for (final text in [
      'ЛИЧНОЕ ВРЕМЯ НА 5 КМ',
      'СТО ТРЕНИРОВОК ЛЮБОГО ТИПА ЗА ВСЁ ВРЕМЯ',
      'МАКСИМАЛЬНАЯ СЕРИЯ',
      '03:35 · СТАРТ ДО РАССВЕТА',
    ]) {
      final fitted = engravingFitToWidth(text, base, maxW);
      expect(widthOf(text, fitted), lessThanOrEqualTo(maxW + .5),
          reason: 'не влезло: «$text»');
    }
  });

  test('короткая подпись не трогается', () {
    const base = TextStyle(fontSize: 8, letterSpacing: 2.2);
    final fitted = engravingFitToWidth('5 КМ', base, 104);
    expect(fitted.fontSize, 8);
  });
}
