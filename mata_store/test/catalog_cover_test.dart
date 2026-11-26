// Обложки разделов (владелец 26.11): фото НАШЕГО товара вместо стока — сначала
// выбранный вручную товар, иначе первый товар раздела с фото; без фото — пусто.
import 'package:flutter_test/flutter_test.dart';
import 'package:sport_store/data/repositories/product_repository.dart';
import 'package:sport_store/models/category.dart';
import 'package:sport_store/models/product.dart';
import 'package:sport_store/providers/catalog_provider.dart';

Product _p(String id, String cat, List<String> imgs) => Product(
      id: id,
      name: 'Товар $id',
      brand: 'МАТА',
      categoryId: cat,
      price: 1000,
      imageUrls: imgs,
      description: '',
      sizes: const ['M'],
      colors: const ['Черный'],
    );

class _Repo extends MockProductRepository {
  @override
  Future<List<Product>> getProducts() async => [
        _p('nophoto', 'shoes', const []),
        _p('first', 'shoes', const ['https://cdn/first.webp']),
        _p('best', 'shoes', const ['https://cdn/best.webp']),
        _p('tee', 'tees', const ['https://cdn/tee.webp']),
      ];
  @override
  Future<List<Category>> getCategories() async => const [];
  @override
  Future<List<Map<String, String>>> getBanners() async => const [];
}

void main() {
  test('обложка: выбранный товар, иначе первый с фото, иначе пусто', () async {
    final catalog = CatalogProvider(_Repo());
    await pumpEventQueue(times: 50);

    expect(catalog.coverFor(['shoes'], preferId: 'best'), 'https://cdn/best.webp');
    expect(catalog.coverFor(['shoes']), 'https://cdn/first.webp');
    // выбранного товара нет (снят с продажи) — первый с фото, а не пусто
    expect(catalog.coverFor(['shoes'], preferId: 'gone'), 'https://cdn/first.webp');
    expect(catalog.coverFor(['bags']), '');
  });
}
