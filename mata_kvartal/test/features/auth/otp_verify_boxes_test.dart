import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/features/auth/presentation/widgets/otp_boxes_style.dart';
import 'package:mata_ui/mata_ui.dart';

Widget _wrap(Widget child) =>
    MaterialApp(home: Scaffold(body: Center(child: child)));

/// Прокрутить время маленькими шагами, чтобы сработали и таймеры
/// (Future.delayed), и кадры анимаций.
Future<void> _pumpFor(WidgetTester tester, Duration total) async {
  const step = Duration(milliseconds: 50);
  var elapsed = Duration.zero;
  while (elapsed < total) {
    await tester.pump(step);
    elapsed += step;
  }
}

void main() {
  testWidgets('успех: полная хореография и вызов onSuccess', (tester) async {
    var success = false;
    var failed = false;

    await tester.pumpWidget(
      _wrap(
        OtpVerifyBoxes(
          style: kvartalOtpBoxesStyle(),
          autofocus: true,
          onSubmit: (code) async {
            expect(code, '1234');
            return true;
          },
          onSuccess: () => success = true,
          onFailed: () => failed = true,
        ),
      ),
    );

    await tester.enterText(find.byType(TextField), '1234');
    // Пауза 260 + разлёт 380 + вращение 1250 + схлопывание 420 +
    // кольца 1300 + задержка 500 = ~4.2 с; берём с запасом.
    await _pumpFor(tester, const Duration(seconds: 6));

    expect(success, isTrue);
    expect(failed, isFalse);
  });

  testWidgets('ошибка: возврат в строку, shake и вызов onFailed', (
    tester,
  ) async {
    var success = false;
    var failed = false;

    await tester.pumpWidget(
      _wrap(
        OtpVerifyBoxes(
          style: kvartalOtpBoxesStyle(),
          autofocus: true,
          onSubmit: (code) async => false,
          onSuccess: () => success = true,
          onFailed: () => failed = true,
        ),
      ),
    );

    await tester.enterText(find.byType(TextField), '9999');
    await _pumpFor(tester, const Duration(seconds: 5));

    expect(success, isFalse);
    expect(failed, isTrue);
    // После ошибки ввод очищен и снова активен.
    final field = tester.widget<TextField>(find.byType(TextField));
    expect(field.enabled, isTrue);
    expect(field.controller?.text, isEmpty);
  });

  testWidgets('reduced motion: без хореографии, сразу результат', (
    tester,
  ) async {
    var success = false;

    await tester.pumpWidget(
      MaterialApp(
        home: MediaQuery(
          data: const MediaQueryData(disableAnimations: true),
          child: Scaffold(
            body: Center(
              child: OtpVerifyBoxes(
   style: kvartalOtpBoxesStyle(),
   autofocus: true,
                onSubmit: (code) async => true,
                onSuccess: () => success = true,
              ),
            ),
          ),
        ),
      ),
    );

    await tester.enterText(find.byType(TextField), '1234');
    await _pumpFor(tester, const Duration(seconds: 2));

    expect(success, isTrue);
  });
}
