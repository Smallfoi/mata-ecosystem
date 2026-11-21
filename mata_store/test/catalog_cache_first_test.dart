// Этап 5 оптимизации (21.11.2026): каталог при запуске — сразу из кэша на
// диске, затем свежий с сервера; каждая часть показывается, как только пришла,
// а не после самого медленного из семи запросов.
import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:sport_store/data/repositories/product_repository.dart';
import 'package:sport_store/models/category.dart';
import 'package:sport_store/models/product.dart';
import 'package:sport_store/providers/catalog_provider.dart';

Product _p(String id) => Product(
      id: id,
      name: 'Товар $id',
      brand: 'МАТА',
      categoryId: 'c',
      price: 1000,
      imageUrls: const [],
      description: '',
      sizes: const ['M'],
      colors: const ['Черный'],
    );

class _Repo extends MockProductRepository implements CatalogCache {
  _Repo({this.snapshot});
  final CatalogSnapshot? snapshot;
  final products = Completer<List<Product>>();
  final brands = Completer<List<String>>();

  @override
  Future<CatalogSnapshot?> cachedSnapshot() async => snapshot;
  @override
  Future<List<Product>> getProducts() => products.future;
  @override
  Future<List<String>> getBrands() => brands.future;
  @override
  Future<List<Category>> getCategories() async =>
      const [Category(id: 'c', name: 'Кроссовки', emoji: '')];
  @override
  Future<List<Map<String, String>>> getBanners() async => const [];
  @override
  Future<List<String>> getSizes() async => const ['M'];
  @override
  Future<PriceRange> getPriceRange() async => const PriceRange(0, 1000);
}

void main() {
  test('каталог из кэша виден сразу, ещё до ответа сервера', () async {
    final repo = _Repo(snapshot: CatalogSnapshot(products: [_p('old')]));
    final catalog = CatalogProvider(repo);
    await pumpEventQueue();

    expect(catalog.products.map((p) => p.id), ['old']);
    expect(catalog.isLoading, isFalse);

    repo.products.complete([_p('new1'), _p('new2')]);
    await pumpEventQueue();
    expect(catalog.products.map((p) => p.id), ['new1', 'new2']);
  });

  test('товары показываются, не дожидаясь медленного запроса брендов', () async {
    final repo = _Repo();
    final catalog = CatalogProvider(repo);
    repo.products.complete([_p('a')]);
    await pumpEventQueue();

    expect(catalog.products.map((p) => p.id), ['a']);
    expect(catalog.isLoading, isFalse);
    expect(catalog.categories, isNotEmpty);

    repo.brands.complete(['МАТА']);
    await pumpEventQueue();
    expect(catalog.brands, ['МАТА']);
  });

  test('без кэша и до ответа — идёт загрузка (экран покажет заглушку)', () async {
    final repo = _Repo();
    final catalog = CatalogProvider(repo);
    await pumpEventQueue();
    expect(catalog.isLoading, isTrue);
    expect(catalog.products, isEmpty);
  });
}
