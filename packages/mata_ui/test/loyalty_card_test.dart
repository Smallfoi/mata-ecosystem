import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:mata_ui/mata_ui.dart';

void main() {
  // Идл-циклы «живой» карты бесконечны, поэтому pumpAndSettle с картой
  // не используем: либо reduced motion (мгновенный флип), либо явные pump.
  Widget wrap(Widget child, {bool reducedMotion = true}) => MaterialApp(
        home: MediaQuery(
          // size обязателен: чистый MediaQueryData даёт Size.zero,
          // и ширина карты (size.width - 40) уходит в минус.
          data: MediaQueryData(
            size: const Size(800, 600),
            disableAnimations: reducedMotion,
          ),
          child: Scaffold(body: Center(child: child)),
        ),
      );

  testWidgets('карта: лицо с баллами, по тапу переворот на QR и обратно', (
    tester,
  ) async {
    await tester.pumpWidget(
      wrap(
        const LoyaltyCard3D(
          balance: 3852,
          levelLabel: 'Платина',
          holderName: 'Михаил Татаринов',
          qrData: 'MATA:LOYALTY:42:3852',
          tier: LoyaltyCardTier.platinum,
        ),
      ),
    );

    // Лицо: баллы и уровень видны, QR ещё нет.
    expect(find.text('3852'), findsOneWidget);
    expect(find.text('ПЛАТИНА'), findsOneWidget);
    expect(find.byType(QrImageView), findsNothing);

    // Тап — переворот (reduced motion: мгновенно): виден QR, лицо скрыто.
    await tester.tap(find.byType(LoyaltyCard3D));
    await tester.pump();
    expect(find.byType(QrImageView), findsOneWidget);
    expect(find.text('3852'), findsNothing);

    // Обратный тап — снова лицо.
    await tester.tap(find.byType(LoyaltyCard3D));
    await tester.pump();
    expect(find.byType(QrImageView), findsNothing);
    expect(find.text('3852'), findsOneWidget);
  });

  testWidgets('тап по QR открывает белый полноэкранный QR, тап — закрывает', (
    tester,
  ) async {
    await tester.pumpWidget(
      wrap(
        const LoyaltyCard3D(
          balance: 500,
          levelLabel: 'Золото',
          holderName: 'Михаил Татаринов',
          qrData: 'MATA:LOYALTY:42:500',
          tier: LoyaltyCardTier.gold,
        ),
      ),
    );

    await tester.tap(find.byType(LoyaltyCard3D));
    await tester.pump();
    await tester.tap(find.byType(QrImageView));
    // Два pump: кадр вставки маршрута в Overlay + кадр перехода.
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.byType(LoyaltyQrFullscreen), findsOneWidget);
    expect(find.text('ПОКАЖИТЕ КАССИРУ'), findsOneWidget);

    await tester.tap(find.byType(LoyaltyQrFullscreen));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.byType(LoyaltyQrFullscreen), findsNothing);
  });

  testWidgets('все четыре уровня строятся со своими материалами', (
    tester,
  ) async {
    for (final (tier, label) in [
      (LoyaltyCardTier.basic, 'Базовый'),
      (LoyaltyCardTier.silver, 'Серебро'),
      (LoyaltyCardTier.gold, 'Золото'),
      (LoyaltyCardTier.platinum, 'Платина'),
    ]) {
      await tester.pumpWidget(
        wrap(
          LoyaltyCard3D(
            balance: 100,
            levelLabel: label,
            holderName: 'Тест',
            qrData: 'MATA:LOYALTY:1:100',
            tier: tier,
          ),
        ),
      );
      expect(find.text(label.toUpperCase()), findsOneWidget);
    }
  });

  testWidgets('живые анимации тикают без ошибок (без reduced motion)', (
    tester,
  ) async {
    await tester.pumpWidget(
      wrap(
        const LoyaltyCard3D(
          balance: 3852,
          levelLabel: 'Платина',
          holderName: 'Михаил Татаринов',
          qrData: 'MATA:LOYALTY:42:3852',
          tier: LoyaltyCardTier.platinum,
        ),
        reducedMotion: false,
      ),
    );
    // Несколько секунд жизни: аврора, лучи, комета — кадры без исключений.
    for (var i = 0; i < 12; i++) {
      await tester.pump(const Duration(milliseconds: 500));
    }
    expect(tester.takeException(), isNull);
    // Снять виджет, чтобы корректно закрыть бесконечный тикер.
    await tester.pumpWidget(const SizedBox());
  });
}
