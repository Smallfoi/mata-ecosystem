// Вкладки витрины в приложении (D-133): «Все · Обувь · Одежда…» и второй ряд групп.
// Данные — как отдаёт GET /v1/showcase; без вкладок — прежний ряд категорий.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sport_store/data/repositories/product_repository.dart';
import 'package:sport_store/models/category.dart';
import 'package:sport_store/models/product.dart';
import 'package:sport_store/models/showcase.dart';
import 'package:sport_store/providers/catalog_provider.dart';
import 'package:sport_store/providers/remote_content_provider.dart';
import 'package:sport_store/providers/wishlist_provider.dart';
import 'package:sport_store/screens/catalog/catalog_screen.dart';

Product _p(String id, String category) => Product(
      id: id,
      name: 'Товар $id',
      brand: 'МАТА',
      categoryId: category,
      price: 1000,
      imageUrls: const [],
      description: '',
      sizes: const ['M'],
      colors: const ['Черный'],
    );

final _json = [
  {
    'id': 'shoes', 'name': 'Обувь', 'count': 3,
    'groups': [
      {'id': 'sneakers', 'name': 'Кроссовки', 'count': 2, 'categoryIds': ['c-sneak']},
      {'id': 'boots', 'name': 'Ботинки', 'count': 1, 'categoryIds': ['c-boot']},
    ],
  },
  {
    'id': 'nutrition', 'name': 'Питание', 'count': 1,
    'groups': [
      {'id': 'gels', 'name': 'Гели и изотоники', 'count': 1, 'categoryIds': ['c-gel']},
    ],
  },
];

class _Repo extends MockProductRepository {
  final List<ShowcaseTab> tabs;
  _Repo(this.tabs);

  @override
  Future<List<ShowcaseTab>> getShowcase() async => tabs;

  @override
  Future<List<Category>> getCategories() async => const [
        Category(id: 'all', name: 'Все', emoji: ''),
        Category(id: 'c-sneak', name: 'Кроссовки', emoji: ''),
        Category(id: 'c-boot', name: 'Ботинки', emoji: ''),
        Category(id: 'c-gel', name: 'Гели', emoji: ''),
      ];

  // Без задержек мок-репозитория: в testWidgets время ненастоящее, и
  // Future.delayed не закончился бы без pump.
  @override
  Future<List<String>> getBrands() async => const ['МАТА'];

  @override
  Future<List<String>> getSizes() async => const ['M'];

  @override
  Future<PriceRange> getPriceRange() async => const PriceRange(1000, 1000);

  @override
  Future<List<Map<String, String>>> getBanners() async => const [];

  @override
  Future<List<Product>> getProducts() async =>
      [_p('s1', 'c-sneak'), _p('s2', 'c-sneak'), _p('b1', 'c-boot'), _p('g1', 'c-gel')];
}

List<ShowcaseTab> _tabs() =>
    [for (final j in _json) ShowcaseTab.fromJson(j)];

Future<CatalogProvider> _loaded(List<ShowcaseTab> tabs) async {
  final catalog = CatalogProvider(_Repo(tabs));
  await catalog.load();
  return catalog;
}

Future<void> _pump(WidgetTester tester, CatalogProvider catalog, {String? initial}) async {
  tester.view.physicalSize = const Size(900, 2400);
  tester.view.devicePixelRatio = 2;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  await tester.pumpWidget(MultiProvider(
    providers: [
      ChangeNotifierProvider.value(value: catalog),
      ChangeNotifierProvider(create: (_) => WishlistProvider(prefs)),
      ChangeNotifierProvider(create: (_) => RemoteContentProvider(null)),
    ],
    child: MaterialApp(home: CatalogScreen(initialCategory: initial)),
  ));
  await tester.pump(const Duration(milliseconds: 500));
}

Set<String> _shownIds(WidgetTester tester) => {
      for (final w in tester.widgetList<Text>(find.textContaining('Товар ')))
        w.data!.replaceFirst('Товар ', ''),
    };

void main() {
  test('ответ /v1/showcase разбирается в вкладки и группы', () {
    final tabs = _tabs();
    expect(tabs.map((t) => t.id), ['shoes', 'nutrition']);
    expect(tabs.first.groups.map((g) => g.name), ['Кроссовки', 'Ботинки']);
    expect(tabs.first.categoryIds, {'c-sneak', 'c-boot'});
  });

  test('товары вкладки и группы, переход по категории', () async {
    final catalog = await _loaded(_tabs());
    expect(catalog.byShowcase('all').length, 4);
    expect(catalog.byShowcase('shoes').map((p) => p.id), ['s1', 's2', 'b1']);
    expect(catalog.byShowcase('shoes', groupId: 'boots').map((p) => p.id), ['b1']);
    final (tab, group) = catalog.placeOfCategory('c-gel');
    expect(tab?.id, 'nutrition');
    expect(group?.id, 'gels');
  });

  testWidgets('вкладка показывает группы, группа фильтрует, повтор снимает',
      (tester) async {
    await _pump(tester, await _loaded(_tabs()));
    expect(find.text('Обувь'), findsOneWidget);
    expect(find.text('Питание'), findsOneWidget);
    expect(find.byKey(const ValueKey('group-sneakers')), findsNothing);
    expect(_shownIds(tester).length, 4);

    await tester.tap(find.byKey(const ValueKey('tab-shoes')));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.byKey(const ValueKey('group-sneakers')), findsOneWidget);
    expect(_shownIds(tester), {'s1', 's2', 'b1'});

    await tester.tap(find.byKey(const ValueKey('group-boots')));
    await tester.pump(const Duration(milliseconds: 300));
    expect(_shownIds(tester), {'b1'});

    await tester.tap(find.byKey(const ValueKey('group-boots')));
    await tester.pump(const Duration(milliseconds: 300));
    expect(_shownIds(tester), {'s1', 's2', 'b1'});

    // Во вкладке с одной группой второй ряд не нужен.
    await tester.tap(find.byKey(const ValueKey('tab-nutrition')));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.byKey(const ValueKey('group-gels')), findsNothing);
    expect(_shownIds(tester), {'g1'});
  });

  testWidgets('переход по категории открывает её вкладку и группу', (tester) async {
    await _pump(tester, await _loaded(_tabs()), initial: 'c-boot');
    expect(_shownIds(tester), {'b1'});
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.byKey(const ValueKey('group-boots')), findsOneWidget);
  });

  testWidgets('без вкладок от бэкенда — прежний ряд категорий', (tester) async {
    await _pump(tester, await _loaded(const []));
    expect(find.byKey(const ValueKey('tab-c-gel')), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('tab-c-gel')));
    await tester.pump(const Duration(milliseconds: 300));
    expect(_shownIds(tester), {'g1'});
  });
}
