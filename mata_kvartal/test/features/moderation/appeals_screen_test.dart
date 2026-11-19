import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/features/moderation/data/appeals_provider.dart';
import 'package:kvartal_app/features/moderation/presentation/appeals_screen.dart';

/// §10 готовности: человек видит меру к себе и может один раз возразить;
/// заявитель видит итог своей жалобы — без подробностей о другом человеке.

class _FakeAppeal extends AppealActions {
  _FakeAppeal(super.ref);
  final sent = <(String, String)>[];

  @override
  Future<String?> appeal(String measureId, String text) async {
    sent.add((measureId, text));
    return null;
  }
}

Future<_FakeAppeal> _pump(
  WidgetTester tester, {
  List<MyMeasure> measures = const [],
  List<MyReport> reports = const [],
}) async {
  tester.view.physicalSize = const Size(1080, 3600);
  tester.view.devicePixelRatio = 2;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        myMeasuresProvider.overrideWith((ref) async => measures),
        myReportsProvider.overrideWith((ref) async => reports),
        appealActionsProvider.overrideWith(_FakeAppeal.new),
      ],
      child: const MaterialApp(home: AppealsScreen()),
    ),
  );
  await tester.pumpAndSettle();
  final c = ProviderScope.containerOf(tester.element(find.byType(AppealsScreen)));
  return c.read(appealActionsProvider) as _FakeAppeal;
}

void main() {
  testWidgets('пусто — экран так и говорит', (tester) async {
    await _pump(tester);
    expect(find.text('Мер нет.'), findsOneWidget);
    expect(find.text('Вы не отправляли жалоб.'), findsOneWidget);
  });

  testWidgets('мера видна с причиной, возражение уходит один раз', (tester) async {
    final fake = await _pump(tester, measures: const [
      MyMeasure(id: '7', kindTitle: 'Предупреждение', summary: 'Оскорбления в чате клуба',
          canAppeal: true),
    ]);
    expect(find.text('Оскорбления в чате клуба'), findsOneWidget);
    expect(find.text('действует'), findsOneWidget);

    await tester.tap(find.text('Возразить'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), 'Это был не я');
    await tester.pump();
    await tester.tap(find.text('Отправить'));
    await tester.pumpAndSettle();

    expect(fake.sent, [('7', 'Это был не я')]);
    expect(find.textContaining('Возражение отправлено'), findsOneWidget);
  });

  testWidgets('разобранное возражение показывает ответ, кнопки нет', (tester) async {
    await _pump(tester, measures: const [
      MyMeasure(id: '8', kindTitle: 'Предупреждение', summary: 'Спам', active: false,
          appealStatus: 'accepted', appealReply: 'Проверили — ошибка.'),
    ]);
    expect(find.text('Возражение принято, мера снята'), findsOneWidget);
    expect(find.text('Ответ модератора: Проверили — ошибка.'), findsOneWidget);
    expect(find.text('Возразить'), findsNothing);
    expect(find.text('снята'), findsOneWidget);
  });

  testWidgets('итог жалобы — без подробностей о другом человеке', (tester) async {
    await _pump(tester, reports: const [
      MyReport(id: '1', targetName: 'Борис', reasonTitle: 'Оскорбления',
          status: 'accepted', statusTitle: 'Приняты меры'),
      MyReport(id: '2', targetName: 'Виктор', reasonTitle: 'Спам',
          status: 'new', statusTitle: 'Новая'),
    ]);
    expect(find.text('Меры приняты. Спасибо, что сообщили.'), findsOneWidget);
    expect(find.text('На разборе. Ответ придёт уведомлением.'), findsOneWidget);
  });
}
