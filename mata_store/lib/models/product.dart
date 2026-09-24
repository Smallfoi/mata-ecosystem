/// Вариант модели: сочетание цвета и размера — это отдельная позиция на складе.
///
/// В 1С каждый размер и цвет ведутся отдельными карточками (так печатают
/// этикетки). Покупатель видит одну карточку модели, но заказ обязан уйти
/// на конкретную позицию — её идентификатор и лежит здесь.
class ProductVariant {
  final String productId;
  final String size;
  final String color;
  final double price;
  final bool inStock;

  const ProductVariant({
    required this.productId,
    required this.size,
    required this.color,
    required this.price,
    required this.inStock,
  });

  factory ProductVariant.fromJson(Map<String, dynamic> j, String color) => ProductVariant(
        productId: j['productId'].toString(),
        size: (j['size'] ?? '').toString(),
        color: color,
        price: (j['price'] as num?)?.toDouble() ?? 0,
        inStock: j['inStock'] as bool? ?? true,
      );

  Map<String, dynamic> toJson() => {
        'productId': productId,
        'size': size,
        'color': color,
        'price': price,
        'inStock': inStock,
      };
}

class Product {
  final String id;
  final String name;
  final String brand;
  final String categoryId;
  final double price;
  final double? oldPrice;
  final List<String> imageUrls;
  final String description;
  final List<String> sizes;
  final List<String> colors;
  final bool isNew;
  final bool isFeatured;
  final double rating;
  final int reviewCount;
  final bool inStock;

  /// Остаток по размерам из 1С: {'41': 0, '42': 7}. Пусто — разбивки нет, и тогда
  /// доступны все размеры (товар заведён руками либо 1С прислала общий остаток).
  final Map<String, int> stockBySize;

  /// Варианты модели (цвет + размер → позиция склада). Пусто — обычный товар
  /// из старого списка позиций, тогда работаем как раньше.
  final List<ProductVariant> variants;

  const Product({
    required this.id,
    required this.name,
    required this.brand,
    required this.categoryId,
    required this.price,
    this.oldPrice,
    required this.imageUrls,
    required this.description,
    required this.sizes,
    required this.colors,
    this.isNew = false,
    this.isFeatured = false,
    this.rating = 0,
    this.reviewCount = 0,
    this.inStock = true,
    this.stockBySize = const {},
    this.variants = const [],
  });

  bool get isOnSale => oldPrice != null && oldPrice! > price;

  /// Позиция склада для выбранного сочетания — её и кладём в заказ.
  ProductVariant? variantFor(String size, String color) {
    for (final v in variants) {
      final sizeOk = v.size == size || (v.size.isEmpty && size.isEmpty);
      final colorOk = v.color == color || (v.color.isEmpty && color.isEmpty);
      if (sizeOk && colorOk) return v;
    }
    return null;
  }

  /// Доступен ли размер у выбранного цвета. Без вариантов — по остаткам, как раньше.
  bool hasSizeInColor(String size, String? color) {
    if (variants.isEmpty || color == null) return hasSize(size);
    final v = variantFor(size, color);
    return v?.inStock ?? false;
  }

  /// Есть ли у цвета хоть один доступный размер.
  bool hasColor(String color) {
    if (variants.isEmpty) return true;
    return variants.any((v) => v.color == color && v.inStock);
  }

  /// Можно ли купить этот размер. Нет разбивки — считаем, что можно: лучше
  /// показать размер и упереться в отказ при заказе, чем спрятать имеющийся.
  bool hasSize(String size) =>
      stockBySize.isEmpty || (stockBySize[size] ?? 0) > 0;

  /// Первое фото или '' (безопасно при пустом списке — напр. данные из API).
  String get firstImage => imageUrls.isNotEmpty ? imageUrls.first : '';

  int get discountPercent {
    if (!isOnSale) return 0;
    return (((oldPrice! - price) / oldPrice!) * 100).round();
  }

  /// Копия с другой позицией склада и ценой — для заказа выбранного варианта.
  Product copyWith({String? id, double? price}) => Product(
        id: id ?? this.id,
        name: name,
        brand: brand,
        categoryId: categoryId,
        price: price ?? this.price,
        oldPrice: oldPrice,
        imageUrls: imageUrls,
        description: description,
        sizes: sizes,
        colors: colors,
        isNew: isNew,
        isFeatured: isFeatured,
        rating: rating,
        reviewCount: reviewCount,
        inStock: inStock,
        stockBySize: stockBySize,
        variants: variants,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'brand': brand,
        'categoryId': categoryId,
        'price': price,
        'oldPrice': oldPrice,
        'imageUrls': imageUrls,
        'description': description,
        'sizes': sizes,
        'colors': colors,
        'isNew': isNew,
        'isFeatured': isFeatured,
        'rating': rating,
        'reviewCount': reviewCount,
        'inStock': inStock,
        'stockBySize': stockBySize,
        'variants': variants.map((v) => v.toJson()).toList(),
      };

  factory Product.fromJson(Map<String, dynamic> j) => Product(
        id: j['id'].toString(),
        name: j['name'] as String,
        brand: j['brand'] as String? ?? '',
        categoryId: j['categoryId'] as String? ?? '',
        price: (j['price'] as num).toDouble(),
        oldPrice: j['oldPrice'] == null ? null : (j['oldPrice'] as num).toDouble(),
        imageUrls: (j['imageUrls'] as List? ?? const []).map((e) => e.toString()).toList(),
        description: j['description'] as String? ?? '',
        sizes: (j['sizes'] as List? ?? const []).map((e) => e.toString()).toList(),
        colors: (j['colors'] as List? ?? const []).map((e) => e.toString()).toList(),
        isNew: j['isNew'] as bool? ?? false,
        isFeatured: j['isFeatured'] as bool? ?? false,
        rating: (j['rating'] as num?)?.toDouble() ?? 0,
        reviewCount: j['reviewCount'] as int? ?? 0,
        inStock: j['inStock'] as bool? ?? true,
        stockBySize: ((j['stockBySize'] as Map?) ?? const {}).map(
          (k, v) => MapEntry(k.toString(), (v as num?)?.toInt() ?? 0),
        ),
        variants: (j['variants'] as List? ?? const [])
            .map((e) => ProductVariant.fromJson(
                e as Map<String, dynamic>, (e['color'] ?? '').toString()))
            .toList(),
      );

  /// Карточка модели из `/v1/models`: один товар — много цветов и размеров.
  ///
  /// Внутри карточки цвета, у каждого свои размеры со своей позицией склада.
  /// Разворачиваем это в плоский список вариантов, а экрану товара отдаём
  /// привычные списки размеров и цветов.
  factory Product.fromModelCard(Map<String, dynamic> j) {
    final colors = (j['colors'] as List? ?? const []).cast<Map<String, dynamic>>();
    final variants = <ProductVariant>[];
    for (final c in colors) {
      final name = (c['name'] ?? '').toString();
      for (final s in (c['sizes'] as List? ?? const [])) {
        variants.add(ProductVariant.fromJson(s as Map<String, dynamic>, name));
      }
    }
    final image = (j['imageUrl'] ?? '').toString();
    return Product(
      id: (j['key'] ?? '').toString(),
      name: (j['name'] ?? '').toString(),
      brand: (j['brand'] ?? '').toString(),
      categoryId: (j['categoryId'] ?? '').toString(),
      price: (j['price'] as num?)?.toDouble() ?? 0,
      oldPrice: j['oldPrice'] == null ? null : (j['oldPrice'] as num).toDouble(),
      imageUrls: image.isEmpty ? const [] : [image],
      description: (j['description'] ?? '').toString(),
      sizes: (j['sizes'] as List? ?? const []).map((e) => e.toString()).toList(),
      colors: colors.map((c) => (c['name'] ?? '').toString()).toList(),
      isNew: j['isNew'] as bool? ?? false,
      isFeatured: j['isFeatured'] as bool? ?? false,
      rating: (j['rating'] as num?)?.toDouble() ?? 0,
      reviewCount: (j['reviewCount'] as num?)?.toInt() ?? 0,
      inStock: j['inStock'] as bool? ?? true,
      variants: variants,
    );
  }
}
