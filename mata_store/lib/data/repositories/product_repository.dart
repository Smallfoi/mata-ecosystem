import '../../models/category.dart';
import '../../models/product.dart';
import '../../models/review.dart';
import '../api/api_client.dart';
import '../api/api_config.dart';
import '../mock_data.dart';

/// Диапазон цен для фильтра.
class PriceRange {
  final double min;
  final double max;
  const PriceRange(this.min, this.max);
}

/// Контракт доступа к товарам и категориям.
///
/// Это «шов» для backend: экраны и провайдеры зависят только от этого
/// интерфейса. Сейчас используется [MockProductRepository], позже —
/// [ApiProductRepository] (переключается в `ApiConfig.useMock`).
abstract class ProductRepository {
  Future<List<Category>> getCategories();
  Future<List<Product>> getProducts();
  Future<List<Product>> getByCategory(String categoryId);
  Future<Product?> getById(String id);
  Future<List<Product>> getFeatured();
  Future<List<Product>> getNew();
  Future<List<Product>> search(String query);
  Future<List<String>> getBrands();
  Future<List<String>> getSizes();
  Future<PriceRange> getPriceRange();
  Future<List<Map<String, String>>> getBanners();

  /// Отзывы товара (+ можно ли оставить свой).
  Future<ProductReviews> getReviews(String productId);

  /// Оставить/обновить свой отзыв (только купившие — иначе бросает).
  Future<void> addReview(String productId,
      {required int rating, required String text, List<String> photos});

  /// Загрузить фото к отзыву → URL (/media/...).
  Future<String> uploadReviewPhoto(String filePath);
}

// ─── Mock-реализация (прототип, офлайн) ───────────────────────────────────────

class MockProductRepository implements ProductRepository {
  // Небольшая задержка имитирует сетевой запрос; для UI почти незаметна.
  static const _delay = Duration(milliseconds: 120);

  @override
  Future<List<Category>> getCategories() async {
    await Future.delayed(_delay);
    return MockData.categories;
  }

  @override
  Future<List<Product>> getProducts() async {
    await Future.delayed(_delay);
    return MockData.products;
  }

  @override
  Future<List<Product>> getByCategory(String categoryId) async {
    await Future.delayed(_delay);
    return MockData.getByCategory(categoryId);
  }

  @override
  Future<Product?> getById(String id) async {
    await Future.delayed(_delay);
    return MockData.getById(id);
  }

  @override
  Future<List<Product>> getFeatured() async {
    await Future.delayed(_delay);
    return MockData.getFeatured();
  }

  @override
  Future<List<Product>> getNew() async {
    await Future.delayed(_delay);
    return MockData.getNew();
  }

  @override
  Future<List<Product>> search(String query) async {
    await Future.delayed(_delay);
    return MockData.search(query);
  }

  @override
  Future<List<String>> getBrands() async => MockData.allBrands;

  @override
  Future<List<String>> getSizes() async => MockData.allSizes;

  @override
  Future<PriceRange> getPriceRange() async =>
      PriceRange(MockData.minPrice, MockData.maxPrice);

  @override
  Future<List<Map<String, String>>> getBanners() async {
    await Future.delayed(_delay);
    return MockData.banners;
  }

  @override
  Future<ProductReviews> getReviews(String productId) async =>
      const ProductReviews();

  @override
  Future<void> addReview(String productId,
      {required int rating,
      required String text,
      List<String> photos = const []}) async {}

  @override
  Future<String> uploadReviewPhoto(String filePath) async => '';
}

// ─── API-реализация (готова к подключению backend) ────────────────────────────
//
// Эндпоинты — пример; согласуются с backend/выгрузкой из 1С. Тело каждого
// метода уже реализовано через ApiClient — останется поднять API и переключить
// ApiConfig.useMock = false.

class ApiProductRepository implements ProductRepository {
  final ApiClient _client;
  ApiProductRepository(this._client);

  /// platform=app → раздельный порядок витрины для приложения (мерчендайзинг
  /// per-channel: данные товара общие, порядок свой). В превью-сборке
  /// (ApiConfig.preview) добавляем ещё ?preview=1 — каталог отдаёт и черновики.
  Map<String, dynamic>? _q([Map<String, dynamic>? base]) {
    final q = <String, dynamic>{...?base, 'platform': 'app'};
    if (ApiConfig.preview) q['preview'] = '1';
    return q;
  }

  @override
  Future<List<Category>> getCategories() async {
    final data = await _client.get('/categories') as List;
    return data.map((j) => Category.fromJson(j as Map<String, dynamic>)).toList();
  }

  /// Витрина показывает МОДЕЛИ: один товар — много цветов и размеров (D-94).
  /// Если бэкенд старый и адреса нет — работаем с прежним списком позиций
  /// (`fallback` — тот адрес, который отвечал раньше).
  Future<List<Product>> _models(
    Map<String, dynamic>? extra, {
    String fallback = '/products',
  }) async {
    try {
      final data = await _client.get('/models', query: _q(extra)) as List;
      return data
          .map((j) => Product.fromModelCard(j as Map<String, dynamic>))
          .toList();
    } catch (_) {
      final data = await _client.get(fallback, query: _q(extra)) as List;
      return data.map((j) => Product.fromJson(j as Map<String, dynamic>)).toList();
    }
  }

  @override
  Future<List<Product>> getProducts() => _models(null);

  @override
  Future<List<Product>> getByCategory(String categoryId) =>
      _models({'category': categoryId});

  /// Витрина открывает карточку МОДЕЛИ по её ключу, избранное и корзина хранят
  /// складскую позицию. Поэтому пробуем модель, а не нашли — обычный товар.
  @override
  Future<Product?> getById(String id) async {
    try {
      final card = await _client.get('/models/$id', query: _q());
      if (card != null) {
        return Product.fromModelCard(card as Map<String, dynamic>);
      }
    } catch (_) {
      // Ключа модели с таким значением нет — значит это позиция склада.
    }
    final data = await _client.get('/products/$id', query: _q());
    if (data == null) return null;
    return Product.fromJson(data as Map<String, dynamic>);
  }

  @override
  Future<List<Product>> getFeatured() => _models({'featured': true});

  @override
  Future<List<Product>> getNew() => _models({'new': true});

  /// Поиск тоже отдаёт модели: иначе по запросу «шорты» выпадут шесть
  /// одинаковых карточек разных размеров.
  @override
  Future<List<Product>> search(String query) =>
      _models({'q': query}, fallback: '/products/search');

  @override
  Future<List<String>> getBrands() async {
    final data = await _client.get('/brands') as List;
    return data.map((e) => e.toString()).toList();
  }

  @override
  Future<List<String>> getSizes() async {
    final data = await _client.get('/sizes') as List;
    return data.map((e) => e.toString()).toList();
  }

  @override
  Future<PriceRange> getPriceRange() async {
    final data = await _client.get('/products/price-range') as Map;
    return PriceRange(
      (data['min'] as num).toDouble(),
      (data['max'] as num).toDouble(),
    );
  }

  @override
  Future<List<Map<String, String>>> getBanners() async {
    final data = await _client.get('/banners', query: _q()) as List;
    return data
        .map((j) => (j as Map).map((k, v) => MapEntry('$k', '$v')))
        .toList();
  }

  @override
  Future<ProductReviews> getReviews(String productId) async {
    final data = await _client.get('/products/$productId/reviews');
    return ProductReviews.fromJson(data as Map<String, dynamic>);
  }

  @override
  Future<void> addReview(String productId,
      {required int rating,
      required String text,
      List<String> photos = const []}) async {
    await _client.post(
      '/products/$productId/reviews',
      body: {'rating': rating, 'text': text, 'photos': photos},
    );
  }

  @override
  Future<String> uploadReviewPhoto(String filePath) async {
    final r = await _client.uploadImage('/reviews/photo', filePath);
    return (r is Map && r['url'] != null) ? r['url'].toString() : '';
  }
}
