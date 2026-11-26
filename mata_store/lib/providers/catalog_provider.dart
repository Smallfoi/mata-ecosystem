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

  /// Обложка раздела — фото НАШЕГО товара, а не сток (владелец 26.11): сначала
  /// выбранный вручную товар [preferId], иначе первый товар раздела с фото (порядок
  /// витрины). Нет ни одного фото — пустая строка (плитку не показываем).
  String coverFor(Iterable<String> categoryIds, {String? preferId}) {
    final ids = categoryIds.toSet();
    if (preferId != null) {
      for (final p in _products) {
        if (p.id == preferId && p.firstImage.isNotEmpty) return p.firstImage;
      }
    }
    for (final p in _products) {
      if (ids.contains(p.categoryId) && p.firstImage.isNotEmpty) return p.firstImage;
    }
    return '';
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
  /// Сначала — каталог с прошлого запуска (с диска, мгновенно), затем свежий с
  /// сервера: каждая часть показывается, как только пришла (этап 5 оптимизации,
  /// 21.11.2026). Раньше главная ждала все семь запросов разом и ничего не
  /// показывала до самого медленного.
  Future<void> load() async {
    _loading = true;
    notifyListeners();

    final repo = _repo;
    if (repo is CatalogCache && _products.isEmpty) {
      final snap = await (repo as CatalogCache).cachedSnapshot();
      if (snap != null) {
        _products = snap.products ?? _products;
        _categories = snap.categories ?? _categories;
        _banners = snap.banners ?? _banners;
        _showcase = snap.showcase ?? _showcase;
        if (_products.isNotEmpty) _loading = false;
        notifyListeners();
      }
    }

    Future<void> part<T>(Future<T> f, void Function(T v) apply) async {
      try {
        apply(await f);
        notifyListeners();
      } catch (_) {
        // Часть каталога недоступна — остальное показываем; пустое место
        // экраны обработают сами.
      }
    }

    await Future.wait([
      part(_repo.getProducts(), (v) {
        _products = v;
        _loading = false;
      }),
      part(_repo.getCategories(), (v) => _categories = v),
      part(_repo.getBanners(), (v) => _banners = v),
      part(_repo.getBrands(), (v) => _brands = v),
      part(_repo.getSizes(), (v) => _sizes = v),
      part(_repo.getPriceRange(), (v) {
        _minPrice = v.min;
        _maxPrice = v.max;
      }),
      part(_repo.getShowcase(), (v) => _showcase = v),
    ]);
    _loading = false;
    notifyListeners();
  }
}
