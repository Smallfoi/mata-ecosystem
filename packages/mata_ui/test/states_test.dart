import 'package:flutter/cupertino.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mata_ui/mata_ui.dart';

/// Единые состояния экрана (пункт «states», D-126/D-127).
void main() {
  Widget wrap(Widget child) => CupertinoApp(
        home: CupertinoPageScaffold(child: child),
      );

  const title = TextStyle(fontSize: 16, fontWeight: FontWeight.w700);
  const hint = TextStyle(fontSize: 14);

  testWidgets('ожидание: одна крутилка, в стиле iOS', (tester) async {
    await tester.pumpWidget(wrap(const MataLoading()));
    expect(find.byType(CupertinoActivityIndicator), findsOneWidget);
  });

  testWidgets('ожидание: цвет и радиус доходят до крутилки', (tester) async {
    await tester.pumpWidget(
      wrap(const MataLoading(color: Color(0xFFDFF45F), radius: 8)),
    );
    final spinner = tester.widget<CupertinoActivityIndicator>(
      find.byType(CupertinoActivityIndicator),
    );
    expect(spinner.radius, 8);
    expect(spinner.color, const Color(0xFFDFF45F));
  });

  testWidgets('пусто: заголовок, пояснение и действие', (tester) async {
    await tester.pumpWidget(wrap(MataEmpty(
      title: 'Пока нет пробежек',
      titleStyle: title,
      hint: 'Первая появится здесь после старта',
      hintStyle: hint,
      icon: CupertinoIcons.circle,
      action: CupertinoButton(onPressed: () {}, child: const Text('Начать')),
    )));
    expect(find.text('Пока нет пробежек'), findsOneWidget);
    expect(find.text('Первая появится здесь после старта'), findsOneWidget);
    expect(find.text('Начать'), findsOneWidget);
  });

  testWidgets('пусто без действия: кнопку не выдумываем', (tester) async {
    await tester.pumpWidget(wrap(const MataEmpty(
      title: 'Ничего не найдено',
      titleStyle: title,
    )));
    expect(find.text('Ничего не найдено'), findsOneWidget);
    expect(find.byType(CupertinoButton), findsNothing);
  });

  testWidgets('пусто: размер иконки один на экосистему', (tester) async {
    await tester.pumpWidget(wrap(const MataEmpty(
      title: 'Пусто',
      icon: CupertinoIcons.bell,
    )));
    final icon = tester.widget<Icon>(find.byType(Icon));
    expect(icon.size, MataStateMetrics.iconSize);
  });

  testWidgets('пусто: текст можно отдать виджетом (RemoteText в Store)',
      (tester) async {
    await tester.pumpWidget(wrap(const MataEmpty(
      titleWidget: Text('Корзина пуста'),
      hintWidget: Text('Добавьте товары из каталога'),
    )));
    expect(find.text('Корзина пуста'), findsOneWidget);
    expect(find.text('Добавьте товары из каталога'), findsOneWidget);
  });

  testWidgets('ошибка: всегда есть «Повторить» и он срабатывает',
      (tester) async {
    var retries = 0;
    await tester.pumpWidget(wrap(MataError(
      title: 'Не удалось загрузить каталог',
      titleStyle: title,
      hint: 'Проверьте интернет и попробуйте ещё раз',
      hintStyle: hint,
      retryLabel: 'Повторить',
      onRetry: () => retries++,
      retryBuilder: (context, label, onTap) =>
          CupertinoButton(onPressed: onTap, child: Text(label)),
    )));
    expect(find.text('Не удалось загрузить каталог'), findsOneWidget);
    expect(find.text('Проверьте интернет и попробуйте ещё раз'), findsOneWidget);

    await tester.tap(find.text('Повторить'));
    await tester.pump();
    expect(retries, 1);
  });
}
