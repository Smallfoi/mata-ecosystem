import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/features/medals/data/medal_defs.dart';
import 'package:kvartal_app/features/medals/data/medals_provider.dart';
import 'package:kvartal_app/features/medals/presentation/medal_share.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Карточки шаринга: собираются без падений, держат сторис-пропорцию
/// и следуют решениям владельца (без пустых слотов, гравировку можно скрыть).
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  MedalFull earned(String id) => MedalFull(
        medalById(id),
        MedalState(
          id: id,
          available: true,
          earnedAtMs: 1757000000000,
          engraving: (v: '0,5 КМ', u: 'ПЕРВЫЙ БЕГ', sub: '05.09.2026'),
        ),
      );

  Widget host(Widget child) => MaterialApp(
        home: Scaffold(body: Center(child: child)),
      );

  testWidgets('сторис-карточка медали 9:16 собирается (v2)', (tester) async {
    await tester.pumpWidget(host(MedalStoryCard(
      medal: earned('d_first_run'),
      runner: 'Михаил Татаринов',
      city: 'Якутск',
      hallEarned: 7,
    )));
    final size = tester.getSize(find.byType(MedalStoryCard));
    expect(size.width / size.height, closeTo(9 / 16, .001));
    expect(find.text('Первый бег'), findsOneWidget);
    // v2: гравировка — капсулой, прогресс зала — хвастовство пути.
    expect(find.text('0,5 КМ · ПЕРВЫЙ БЕГ'), findsOneWidget);
    expect(find.text('ШТАМП МАТА · МЕДАЛЬ 7 ИЗ ${kMedals.length}'),
        findsOneWidget);
    // Подпись бренда — вариант А (без слогана и ссылки, решение 06.09.2026).
    expect(find.byType(BrandMark), findsOneWidget);
    expect(find.text('КВАРТАЛ'), findsOneWidget);
    expect(find.textContaining('mata-club.ru'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('стикер: гравировка скрывается переключателем', (tester) async {
    await tester.pumpWidget(host(MedalSticker(
      medal: earned('d_dawn'),
      engraving: true,
    )));
    expect(find.textContaining('0,5 КМ'), findsOneWidget);

    await tester.pumpWidget(host(MedalSticker(
      medal: earned('d_dawn'),
      engraving: false,
    )));
    expect(find.textContaining('0,5 КМ'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'шит: «Сохранить в галерею» всегда, подсказка про фон — в режиме стикера',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    await tester.pumpWidget(ProviderScope(
      child: MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => Center(
              child: FilledButton(
                onPressed: () =>
                    showMedalShareSheet(context, earned('d_first_run')),
                child: const Text('открыть'),
              ),
            ),
          ),
        ),
      ),
    ));
    await tester.tap(find.text('открыть'));
    await tester.pumpAndSettle();

    // Путь «как у Стравы»: сохранение доступно и для карточки, и для стикера.
    expect(find.text('Сохранить в галерею'), findsOneWidget);
    expect(find.byType(StickerHint), findsNothing);

    await tester.tap(find.text('Стикер на своё фото'));
    await tester.pumpAndSettle();
    expect(find.byType(StickerHint), findsOneWidget);
    expect(find.text('Сохранить в галерею'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('карточка зала — без пустых слотов, счёт N из 44',
      (tester) async {
    final medals = [
      earned('d_first_run'),
      earned('d_dawn'),
      earned('t_defense_7'),
      // Незаработанная — на карточку попасть не должна.
      MedalFull(
        medalById('s_champion'),
        const MedalState(id: 's_champion', available: true),
      ),
    ];
    await tester.pumpWidget(host(HallStoryCard(
      medals: medals,
      runner: 'Михаил Татаринов',
    )));
    expect(find.text('3 из ${kMedals.length} · Штамп МАТА'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
