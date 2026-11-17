import 'package:flutter/foundation.dart' hide Category;
import '../data/repositories/product_repository.dart';
import '../models/category.dart';
import '../models/product.dart';
import '../models/review.dart';
import '../models/showcase.dart';

/// Кэширует каталог, загруженный из [ProductRepository], и отдаёт его экранам
/// синхронно. Источник (mock/API) задаётся при создании репозитория в main.dart,
/// поэтому переход на backend не затрагивает экраны.
class CatalogProvider extends ChangeNotifier {
  final ProductRepository _repo;

  CatalogProvider(this._repo) {
    load();
  }

  bool _loading = true;
  bool get isLoading => _loading;
  bool get isReady => !_loading;

  List<Product> _products = const [];
  List<Category> _categories = const [];
  List<ShowcaseTab> _showcase = const [];
  List<Map<String, String>> _banners = const [];
  List<String> _brands = const [];
  List<String> _sizes = const [];
  double _minPrice = 0;
  double _maxPrice = 0;

  // ── Синхронный доступ для экранов ────────────────────────────────────────
  List<Product> get products => _products;
  List<Category> get categories => _categories;
  List<ShowcaseTab> get showcase => _showcase;
  List<Map<String, String>> get banners => _banners;
  List<String> get brands => _brands;
  List<String> get sizes => _sizes;
  double get minPrice => _minPrice;
  double get maxPrice => _maxPrice;

  List<Product> get featured =>
      _products.where((p) => p.isFeatured).toList();
  List<Product> get newProducts =>
      _products.where((p) => p.isNew).toList();

  List<Product> byCategory(String categoryId) {
    if (categoryId == 'all') return _products;
    return _products.where((p) => p.categoryId == categoryId).toList();
  }

  ShowcaseTab? tabById(String id) {
    for (final t in _showcase) {
      if (t.id == id) return t;
    }
    return null;
  }

  /// Вкладка и группа, в которые попадает категория 1С (для перехода в каталог
  /// по категории — например, с главной). Нет во вкладках — (null, null).
  (ShowcaseTab?, ShowcaseGroup?) placeOfCategory(String categoryId) {
    for (final t in _showcase) {
      for (final g in t.groups) {
        if (g.categoryIds.contains(categoryId)) return (t, g);
      }
    }
    return (null, null);
  }

  /// Товары вкладки, а внутри неё — группы. `tabId == 'all'` — весь каталог.
  List<Product> byShowcase(String tabId, {String? groupId}) {
    if (tabId == 'all') return _products;
    final tab = tabById(tabId);
    if (tab == null) return byCategory(tabId);
    Set<String> ids = tab.categoryIds;
    if (groupId != null) {
      for (final g in tab.groups) {
        if (g.id == groupId) ids = g.categoryIds.toSet();
      }
    }
    return _products.where((p) => ids.contains(p.categoryId)).toList();
  }

  Product? getById(String id) {
    for (final p in _products) {
      if (p.id == id) return p;
    }
    return null;
  }

  List<Product> search(String query) {
    final q = query.toLowerCase();
    return _products.where((p) {
      return p.name.toLowerCase().contains(q) ||
          p.description.toLowerCase().contains(q) ||
          p.brand.toLowerCase().contains(q);
    }).toList();
  }

  Category? categoryById(String id) {
    for (final c in _categories) {
      if (c.id == id) return c;
    }
    return null;
  }

  // ── Отзывы ───────────────────────────────────────────────────────────────
  Future<ProductReviews> getReviews(String productId) =>
      _repo.getReviews(productId);

  /// Загрузить фото к отзыву → URL (для прикрепления к отзыву).
  Future<String> uploadReviewPhoto(String filePath) =>
      _repo.uploadReviewPhoto(filePath);

  /// Оставить отзыв → обновить рейтинг товара в кэше → вернуть свежие отзывы.
  Future<ProductReviews> submitReview(String productId,
      {required int rating,
      required String text,
      List<String> photos = const []}) async {
    await _repo.addReview(productId, rating: rating, text: text, photos: photos);
    final fresh = await _repo.getById(productId);
    if (fresh != null) {
      _products =
          _products.map((p) => p.id == productId ? fresh : p).toList();
      notifyListeners();
    }
    return _repo.getReviews(productId);
  }

  // ── Загрузка ─────────────────────────────────────────────────────────────
  Future<void> load() async {
    _loading = true;
    notifyListeners();
    try {
      final results = await Future.wait([
        _repo.getProducts(),
        _repo.getCategories(),
        _repo.getBanners(),
        _repo.getBrands(),
        _repo.getSizes(),
        _repo.getPriceRange(),
        _repo.getShowcase(),
      ]);
      _products = results[0] as List<Product>;
      _categories = results[1] as List<Category>;
      _banners = results[2] as List<Map<String, String>>;
      _brands = results[3] as List<String>;
      _sizes = results[4] as List<String>;
      final range = results[5] as PriceRange;
      _minPrice = range.min;
      _maxPrice = range.max;
      _showcase = results[6] as List<ShowcaseTab>;
    } catch (_) {
      // Каталог недоступен — оставляем пустым; экраны покажут пустое состояние.
    }
    _loading = false;
    notifyListeners();
  }
}
