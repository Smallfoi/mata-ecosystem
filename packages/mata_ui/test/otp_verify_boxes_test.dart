import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mata_ui/mata_ui.dart';

/// Два заведомо разных стиля: виджет обязан брать цвета ТОЛЬКО из стиля.
const _light = OtpBoxesStyle(
  accent: Color(0xFF111111),
  currentShadow: Color(0x1F111111),
  currentShadowBlur: 14,
  filledBorder: Color(0xFF222222),
  emptyBorder: Color(0xFF333333),
  cellBackground: Color(0xFFFFFFFF),
  digit: Color(0xFF111111),
  error: Color(0xFFE53935),
  success: Color(0xFF2E7D32),
  verifiedBackground: Color(0xFFEAF4EC),
  verifiedShadow: Color(0x4D2E7D32),
  spark: Color(0xFF66BB6A),
  cursorRequiresFocus: true,
);

const _dark = OtpBoxesStyle(
  accent: Color(0xFF9CC9BF),
  currentShadow: Color(0x409CC9BF),
  currentShadowBlur: 18,
  filledBorder: Color(0x669CC9BF),
  emptyBorder: Color(0xFF343B35),
  cellBackground: Color(0xFF2A302C),
  digit: Color(0xFFEDEFE8),
  error: Color(0xFFE08A73),
  success: Color(0xFF9CD89A),
  verifiedBackground: Color(0x1F9CD89A),
  verifiedShadow: Color(0x669CD89A),
  spark: Color(0xFF4ADE80),
);

Widget _wrap(Widget child, {bool reducedMotion = false}) => MaterialApp(
  home: MediaQuery(
    data: MediaQueryData(
      size: const Size(800, 600),
      disableAnimations: reducedMotion,
    ),
    child: Scaffold(body: Center(child: child)),
  ),
);

Future<void> _pumpFor(WidgetTester tester, Duration total) async {
  const step = Duration(milliseconds: 50);
  var elapsed = Duration.zero;
  while (elapsed < total) {
    await tester.pump(step);
    elapsed += step;
  }
}

/// Декорации ячеек (60×72) в порядке отрисовки.
List<BoxDecoration> _cells(WidgetTester tester) => tester
    .widgetList<Container>(find.byType(Container))
    .where((c) => c.constraints?.maxWidth == 60 && c.constraints?.maxHeight == 72)
    .map((c) => c.decoration! as BoxDecoration)
    .toList();

void main() {
  testWidgets('цвета ячеек берутся из стиля (два разных стиля)', (
    tester,
  ) async {
    for (final style in [_light, _dark]) {
      await tester.pumpWidget(
        _wrap(
          OtpVerifyBoxes(
            key: UniqueKey(),
            style: style,
            length: 6,
            onSubmit: (_) async => true,
            onSuccess: () {},
          ),
        ),
      );
      final cells = _cells(tester);
      expect(cells, hasLength(6));
      for (final d in cells) {
        expect(d.color, style.cellBackground);
      }
    }
  });

  testWidgets('cursorRequiresFocus: без фокуса текущая ячейка не подсвечена', (
    tester,
  ) async {
    Future<Color> firstBorder(OtpBoxesStyle style) async {
      await tester.pumpWidget(
        _wrap(
          OtpVerifyBoxes(
            key: UniqueKey(),
            style: style,
            onSubmit: (_) async => true,
            onSuccess: () {},
          ),
        ),
      );
      return (_cells(tester).first.border! as Border).top.color;
    }

    // Store-поведение: фокуса нет — первая ячейка как пустая.
    expect(await firstBorder(_light), _light.emptyBorder);
    // Квартал-поведение: текущая ячейка подсвечена акцентом всегда.
    expect(await firstBorder(_dark), _dark.accent);
  });

  testWidgets('autofocus и успех: хореография доходит до onSuccess', (
    tester,
  ) async {
    var success = false;
    await tester.pumpWidget(
      _wrap(
        OtpVerifyBoxes(
          style: _dark,
          autofocus: true,
          onSubmit: (code) async {
            expect(code, '1234');
            return true;
          },
          onSuccess: () => success = true,
        ),
      ),
    );
    await tester.pump();
    final field = tester.widget<TextField>(find.byType(TextField));
    expect(field.autofocus, isTrue);
    expect(field.focusNode!.hasFocus, isTrue);

    await tester.enterText(find.byType(TextField), '1234');
    await _pumpFor(tester, const Duration(seconds: 6));
    expect(success, isTrue);
    // Финал: одна ячейка с фоном успеха из стиля.
    final cells = _cells(tester);
    expect(cells, hasLength(1));
    expect(cells.single.color, _dark.verifiedBackground);
  });

  testWidgets('ошибка (reduced motion): onFailed и ввод очищен', (
    tester,
  ) async {
    var failed = false;
    await tester.pumpWidget(
      _wrap(
        OtpVerifyBoxes(
          style: _light,
          onSubmit: (_) async => false,
          onSuccess: () {},
          onFailed: () => failed = true,
        ),
        reducedMotion: true,
      ),
    );
    await tester.enterText(find.byType(TextField), '9999');
    await _pumpFor(tester, const Duration(seconds: 1));
    expect(failed, isTrue);
    final field = tester.widget<TextField>(find.byType(TextField));
    expect(field.enabled, isTrue);
    expect(field.controller?.text, isEmpty);
  });
}
