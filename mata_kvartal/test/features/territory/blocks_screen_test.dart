import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/features/territory/data/blocks_summary_provider.dart';
import 'package:kvartal_app/features/territory/presentation/blocks_screen.dart';

/// «Мои кварталы» (D-74, Ф3б+Ф4): счёт сезона, дом, районы, клубы.
/// Экран обязан честно говорить, что дом виден другим только как занятый, и не
/// ставить дом на чужой квартал (сервер ответит 409, но человек должен понять
/// заранее, что делать).

class _FakeHome extends HomeActions {
  _FakeHome(super.ref, this.here);
  final BlockHere? here;
  final set = <String>[];

  @override
  Future<BlockHere?> blockHere() async => here;

  @override
  Future<void> setHome(String blockId) async => set.add(blockId);
}

BlocksSummary _summary({HomeBlock? home, int mine = 3}) => BlocksSummary.fromJson({
  'season': {
    'startMs': 0,
    'endMs': DateTime.now().add(const Duration(days: 5)).millisecondsSinceEpoch,
  },
  'mine': mine,
  'total': 632,
  'cityPercent': 0.5,
  'home': home == null ? null : {'blockId': home.blockId, 'district': home.district},
  'districts': [
    {'district': 'Центральный', 'total': 80, 'mine': mine, 'taken': 9,
      'leader': {'name': 'Айсен', 'blocks': 5, 'isMe': false}},
    {'district': 'Строительный', 'total': 60, 'mine': 0, 'taken': 0, 'leader': null},
  ],
  'clubs': [
    {'clubId': 'c1', 'name': 'Северный ветер', 'blocks': 7, 'place': 1, 'isMine': true},
  ],
  'myClubId': 'c1',
});

Future<_FakeHome> _pump(WidgetTester tester, BlocksSummary s, {BlockHere? here}) async {
  // Высокий экран: весь список виден без прокрутки.
  tester.view.physicalSize = const Size(1080, 4000);
  tester.view.devicePixelRatio = 2;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        blocksSummaryProvider.overrideWith((ref) async => s),
        homeActionsProvider.overrideWith((ref) => _FakeHome(ref, here)),
      ],
      child: const MaterialApp(home: BlocksScreen()),
    ),
  );
  await tester.pumpAndSettle();
  final container =
      ProviderScope.containerOf(tester.element(find.byType(BlocksScreen)));
  return container.read(homeActionsProvider) as _FakeHome;
}

void main() {
  testWidgets('счёт сезона, районы и клубы', (tester) async {
    await _pump(tester, _summary());

    expect(find.text(' из 632'), findsNothing); // число и «из» — одна строка
    expect(find.textContaining('из 632'), findsOneWidget);
    expect(find.text('0,5% города'), findsOneWidget);
    expect(find.textContaining('ещё 5 дней'), findsOneWidget);
    expect(find.text('Лидер — Айсен · 5'), findsOneWidget);
    expect(find.text('Район свободен — лидера нет'), findsOneWidget);
    expect(find.text('Северный ветер · ваш клуб'), findsOneWidget);
  });

  testWidgets('без кварталов экран объясняет, как взять первый', (tester) async {
    await _pump(tester, _summary(mine: 0));
    expect(find.textContaining('режиме «Захват»'), findsOneWidget);
  });

  testWidgets('дом ставится на свободный квартал после подтверждения', (tester) async {
    final fake = await _pump(
      tester,
      _summary(),
      here: const BlockHere(blockId: 'b42', district: 'Центральный', canBeHome: true),
    );
    expect(find.text('Дом не выбран'), findsOneWidget);

    await tester.tap(find.text('Сделать домом квартал, где я стою'));
    await tester.pumpAndSettle();
    expect(find.textContaining('не видят, что он ваш'), findsOneWidget);

    await tester.tap(find.text('Сделать домом'));
    await tester.pumpAndSettle();
    expect(fake.set, ['b42']);
  });

  testWidgets('на занятый квартал дом не ставится и объясняется почему', (tester) async {
    final fake = await _pump(
      tester,
      _summary(home: const HomeBlock(blockId: 'b1', district: 'Центральный')),
      here: const BlockHere(blockId: 'b9', canBeHome: false),
    );
    expect(find.text('Домашний квартал'), findsOneWidget);

    await tester.tap(find.text('Сменить на квартал, где я стою'));
    await tester.pumpAndSettle();

    expect(find.textContaining('Этот квартал занят'), findsOneWidget);
    expect(fake.set, isEmpty);
  });
}
