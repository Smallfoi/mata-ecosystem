import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sport_store/theme/text_scale.dart';

void main() {
  testWidgets('огромный системный шрифт ограничен до kMaxTextScale',
      (tester) async {
    late double scaled;
    await tester.pumpWidget(
      MediaQuery(
        data: const MediaQueryData(textScaler: TextScaler.linear(3.0)),
        child: MaterialApp(
          builder: clampTextScale,
          home: Builder(builder: (context) {
            scaled = MediaQuery.textScalerOf(context).scale(10);
            return const SizedBox();
          }),
        ),
      ),
    );
    expect(scaled, closeTo(10 * kMaxTextScale, 0.001));
  });

  testWidgets('обычный и уменьшенный шрифт не трогаем', (tester) async {
    late double scaled;
    await tester.pumpWidget(
      MediaQuery(
        data: const MediaQueryData(textScaler: TextScaler.linear(0.9)),
        child: MaterialApp(
          builder: clampTextScale,
          home: Builder(builder: (context) {
            scaled = MediaQuery.textScalerOf(context).scale(10);
            return const SizedBox();
          }),
        ),
      ),
    );
    expect(scaled, closeTo(9, 0.001));
  });
}