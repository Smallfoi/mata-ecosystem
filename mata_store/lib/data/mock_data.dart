import '../models/category.dart';
import '../models/product.dart';

class MockData {
  static const List<Category> categories = [
    Category(id: 'all', name: 'Все', emoji: '⚡'),
    Category(id: 'tshirts', name: 'Футболки', emoji: '👕'),
    Category(id: 'hoodies', name: 'Худи', emoji: '🧥'),
    Category(id: 'pants', name: 'Брюки', emoji: '👖'),
    Category(id: 'jackets', name: 'Куртки', emoji: '🧤'),
    Category(id: 'shoes', name: 'Кроссовки', emoji: '👟'),
    Category(id: 'accessories', name: 'Аксессуары', emoji: '🎒'),
  ];

  static const List<Product> products = [
    Product(
      id: '1',
      name: 'Беговая футболка Pro Dry',
      brand: 'МАТА',
      categoryId: 'tshirts',
      price: 2990,
      oldPrice: 4500,
      imageUrls: [
        'assets/images/products/1521572163474-6864f9cf17ab.jpg',
        'assets/images/products/1542291026-7eec264c27ff.jpg',
        'assets/images/products/1542291026-7eec264c27ff.jpg',
      ],
      description:
          'Лёгкая беговая футболка из влагоотводящего материала. Идеально подходит для интенсивных тренировок и бега на длинные дистанции. Технология Dry-Fit обеспечивает максимальный комфорт.',
      sizes: ['XS', 'S', 'M', 'L', 'XL', 'XXL'],
      colors: ['Белый', 'Чёрный', 'Серый'],
      isNew: true,
      isFeatured: true,
      rating: 4.8,
      reviewCount: 124,
    ),
    Product(
      id: '2',
      name: 'Худи Essential Fleece',
      brand: 'UrbanFit',
      categoryId: 'hoodies',
      price: 5990,
      imageUrls: [
        'assets/images/products/1620799140408-edc6dcb6d633.jpg',
        'assets/images/products/1542291026-7eec264c27ff.jpg',
      ],
      description:
          'Тёплое флисовое худи для повседневной носки и тренировок в холодную погоду. Кенгуру-карман, регулируемый капюшон. Мягкий внутренний флис согревает в любую погоду.',
      sizes: ['S', 'M', 'L', 'XL', 'XXL'],
      colors: ['Чёрный', 'Серый меланж', 'Тёмно-синий'],
      isFeatured: true,
      rating: 4.9,
      reviewCount: 89,
    ),
    Product(
      id: '3',
      name: 'Кроссовки Air Runner X1',
      brand: 'RunTech',
      categoryId: 'shoes',
      price: 12990,
      oldPrice: 15990,
      imageUrls: [
        'assets/images/products/1542291026-7eec264c27ff.jpg',
        'assets/images/products/1542291026-7eec264c27ff.jpg',
        'assets/images/products/1542291026-7eec264c27ff.jpg',
      ],
      description:
          'Профессиональные беговые кроссовки с амортизирующей подошвой. Сетчатый верх обеспечивает вентиляцию. Идеальны для бега по асфальту и дорожке.',
      sizes: ['39', '40', '41', '42', '43', '44', '45'],
      colors: ['Белый/Чёрный', 'Чёрный/Серый', 'Серый/Белый'],
      isNew: true,
      isFeatured: true,
      rating: 4.7,
      reviewCount: 203,
    ),
    Product(
      id: '4',
      name: 'Спортивные брюки Taper Fit',
      brand: 'МАТА',
      categoryId: 'pants',
      price: 4490,
      imageUrls: [
        'assets/images/products/1506629082955-511b1aa562c8.jpg',
        'assets/images/products/1542291026-7eec264c27ff.jpg',
      ],
      description:
          'Зауженные спортивные брюки с эластичным поясом. Боковые карманы на молнии. Подходят для тренировок и повседневной носки.',
      sizes: ['XS', 'S', 'M', 'L', 'XL', 'XXL'],
      colors: ['Чёрный', 'Тёмно-серый', 'Антрацит'],
      rating: 4.6,
      reviewCount: 67,
    ),
    Product(
      id: '5',
      name: 'Ветровка Shield Pro',
      brand: 'ProGear',
      categoryId: 'jackets',
      price: 8990,
      oldPrice: 11990,
      imageUrls: [
        'assets/images/products/1591047139829-d91aecb6caea.jpg',
        'assets/images/products/1542291026-7eec264c27ff.jpg',
      ],
      description:
          'Лёгкая ветрозащитная куртка с водоотталкивающим покрытием. Упаковывается в собственный карман. Светоотражающие элементы для безопасности.',
      sizes: ['S', 'M', 'L', 'XL', 'XXL'],
      colors: ['Чёрный', 'Тёмно-синий', 'Хаки'],
      isNew: true,
      rating: 4.8,
      reviewCount: 45,
    ),
    Product(
      id: '6',
      name: 'Компрессионная футболка',
      brand: 'RunTech',
      categoryId: 'tshirts',
      price: 3490,
      imageUrls: [
        'assets/images/products/1542291026-7eec264c27ff.jpg',
        'assets/images/products/1542291026-7eec264c27ff.jpg',
        'assets/images/products/1542291026-7eec264c27ff.jpg',
      ],
      description:
          'Компрессионная футболка с длинным рукавом. Поддерживает мышцы во время интенсивных тренировок. Анатомический крой по фигуре.',
      sizes: ['S', 'M', 'L', 'XL'],
      colors: ['Чёрный', 'Белый'],
      rating: 4.5,
      reviewCount: 38,
    ),
    Product(
      id: '7',
      name: 'Рюкзак Training Pack 25L',
      brand: 'UrbanFit',
      categoryId: 'accessories',
      price: 6990,
      imageUrls: [
        'assets/images/products/1553062407-98eeb64c6a62.jpg',
        'assets/images/products/1542291026-7eec264c27ff.jpg',
        'assets/images/products/1542291026-7eec264c27ff.jpg',
      ],
      description:
          'Вместительный спортивный рюкзак объёмом 25 литров. Отдельное отделение для обуви, карман для ноутбука, боковые карманы для бутылок.',
      sizes: ['Один размер'],
      colors: ['Чёрный', 'Серый', 'Хаки'],
      isFeatured: true,
      rating: 4.7,
      reviewCount: 91,
    ),
    Product(
      id: '8',
      name: 'Зимняя куртка Thermo Pro',
      brand: 'ProGear',
      categoryId: 'jackets',
      price: 14990,
      imageUrls: [
        'assets/images/products/1542291026-7eec264c27ff.jpg',
        'assets/images/products/1542291026-7eec264c27ff.jpg',
      ],
      description:
          'Тёплая зимняя куртка с утеплителем PrimaLoft. Водонепроницаемое покрытие, проклеенные швы. Для экстремальных зимних тренировок и активного отдыха.',
      sizes: ['S', 'M', 'L', 'XL', 'XXL'],
      colors: ['Чёрный', 'Тёмно-синий'],
      rating: 4.9,
      reviewCount: 156,
    ),
    Product(
      id: '9',
      name: 'Кроссовки Cloud Foam',
      brand: 'RunTech',
      categoryId: 'shoes',
      price: 9990,
      oldPrice: 12990,
      imageUrls: [
        'assets/images/products/1542291026-7eec264c27ff.jpg',
        'assets/images/products/1542291026-7eec264c27ff.jpg',
        'assets/images/products/1542291026-7eec264c27ff.jpg',
      ],
      description:
          'Лёгкие кроссовки с пеной Cloud Foam для максимальной амортизации. Дышащий верх и гибкая подошва. Идеальны для зала и повседневной носки.',
      sizes: ['38', '39', '40', '41', '42', '43', '44'],
      colors: ['Пастельный', 'Белый/Серый', 'Розовый'],
      isNew: true,
      isFeatured: true,
      rating: 4.7,
      reviewCount: 58,
    ),
    Product(
      id: '10',
      name: 'Кроссовки Street Pro',
      brand: 'ProGear',
      categoryId: 'shoes',
      price: 11490,
      imageUrls: [
        'assets/images/products/1542291026-7eec264c27ff.jpg',
        'assets/images/products/1542291026-7eec264c27ff.jpg',
        'assets/images/products/1542291026-7eec264c27ff.jpg',
      ],
      description:
          'Городские кроссовки с усиленной пяткой и износостойкой подошвой. Универсальный дизайн для спорта и улицы.',
      sizes: ['40', '41', '42', '43', '44', '45'],
      colors: ['Хаки', 'Бело-оранжевый', 'Бордовый'],
      isFeatured: true,
      rating: 4.6,
      reviewCount: 74,
    ),
    Product(
      id: '11',
      name: 'Лонгслив Active Long',
      brand: 'UrbanFit',
      categoryId: 'tshirts',
      price: 3290,
      imageUrls: [
        'assets/images/products/1542291026-7eec264c27ff.jpg',
        'assets/images/products/1542291026-7eec264c27ff.jpg',
      ],
      description:
          'Лонгслив свободного кроя из плотного хлопка. Подходит для прохладной погоды и многослойных образов.',
      sizes: ['XS', 'S', 'M', 'L', 'XL'],
      colors: ['Оранжевый', 'Чёрный', 'Белый'],
      isNew: true,
      rating: 4.5,
      reviewCount: 31,
    ),
    Product(
      id: '12',
      name: 'Футболка Statement',
      brand: 'МАТА',
      categoryId: 'tshirts',
      price: 2490,
      oldPrice: 3290,
      imageUrls: [
        'assets/images/products/1542291026-7eec264c27ff.jpg',
        'assets/images/products/1542291026-7eec264c27ff.jpg',
        'assets/images/products/1542291026-7eec264c27ff.jpg',
      ],
      description:
          'Хлопковая футболка с фирменным принтом. Прямой крой, плотный материал, насыщенный цвет после стирок.',
      sizes: ['S', 'M', 'L', 'XL', 'XXL'],
      colors: ['Белый', 'Бежевый', 'Чёрный'],
      rating: 4.4,
      reviewCount: 47,
    ),
    Product(
      id: '13',
      name: 'Шорты Denim Flex',
      brand: 'UrbanFit',
      categoryId: 'pants',
      price: 3990,
      imageUrls: [
        'assets/images/products/1542291026-7eec264c27ff.jpg',
        'assets/images/products/1542291026-7eec264c27ff.jpg',
      ],
      description:
          'Джинсовые шорты с эластаном для свободы движений. Универсальная посадка, потёртости ручной работы.',
      sizes: ['XS', 'S', 'M', 'L', 'XL'],
      colors: ['Светлый деним', 'Тёмный деним'],
      isNew: true,
      rating: 4.3,
      reviewCount: 22,
    ),
    Product(
      id: '14',
      name: 'Куртка Shearling Winter',
      brand: 'ProGear',
      categoryId: 'jackets',
      price: 16990,
      oldPrice: 21990,
      imageUrls: [
        'assets/images/products/1542291026-7eec264c27ff.jpg',
        'assets/images/products/1542291026-7eec264c27ff.jpg',
      ],
      description:
          'Утеплённая куртка с меховой подкладкой шерпа. Защищает от ветра и мороза, сохраняя стиль. Премиальная фурнитура.',
      sizes: ['S', 'M', 'L', 'XL'],
      colors: ['Коричневый', 'Чёрный'],
      isFeatured: true,
      rating: 4.8,
      reviewCount: 63,
    ),
    Product(
      id: '15',
      name: 'Бутылка Thermo 750 мл',
      brand: 'МАТА',
      categoryId: 'accessories',
      price: 1490,
      imageUrls: [
        'assets/images/products/1542291026-7eec264c27ff.jpg',
      ],
      description:
          'Спортивная термобутылка из нержавеющей стали. Сохраняет холод 24 ч и тепло 12 ч. Матовое покрытие soft-touch.',
      sizes: ['750 мл'],
      colors: ['Зелёный', 'Чёрный', 'Белый'],
      isNew: true,
      rating: 4.9,
      reviewCount: 112,
    ),
    Product(
      id: '16',
      name: 'Рюкзак Urban Daypack',
      brand: 'UrbanFit',
      categoryId: 'accessories',
      price: 5490,
      imageUrls: [
        'assets/images/products/1542291026-7eec264c27ff.jpg',
        'assets/images/products/1553062407-98eeb64c6a62.jpg',
      ],
      description:
          'Городской рюкзак на каждый день с отделением для ноутбука 15". Водоотталкивающая ткань, эргономичные лямки.',
      sizes: ['Один размер'],
      colors: ['Серый', 'Чёрный'],
      rating: 4.6,
      reviewCount: 39,
    ),
  ];

  static List<Product> getByCategory(String categoryId) {
    if (categoryId == 'all') return products;
    return products.where((p) => p.categoryId == categoryId).toList();
  }

  /// Все уникальные бренды, отсортированные по алфавиту.
  static List<String> get allBrands {
    final set = products.map((p) => p.brand).toSet().toList();
    set.sort();
    return set;
  }

  /// Все уникальные размеры (кроме «Один размер»), в естественном порядке.
  static List<String> get allSizes {
    const order = [
      'XS', 'S', 'M', 'L', 'XL', 'XXL',
      '39', '40', '41', '42', '43', '44', '45',
    ];
    final set = <String>{};
    for (final p in products) {
      for (final s in p.sizes) {
        if (s != 'Один размер') set.add(s);
      }
    }
    final list = set.toList()
      ..sort((a, b) {
        final ia = order.indexOf(a);
        final ib = order.indexOf(b);
        if (ia == -1 && ib == -1) return a.compareTo(b);
        if (ia == -1) return 1;
        if (ib == -1) return -1;
        return ia.compareTo(ib);
      });
    return list;
  }

  /// Минимальная и максимальная цена среди всех товаров.
  static double get minPrice =>
      products.map((p) => p.price).reduce((a, b) => a < b ? a : b);
  static double get maxPrice =>
      products.map((p) => p.price).reduce((a, b) => a > b ? a : b);

  static List<Product> getFeatured() {
    return products.where((p) => p.isFeatured).toList();
  }

  static List<Product> getNew() {
    return products.where((p) => p.isNew).toList();
  }

  static List<Product> search(String query) {
    final q = query.toLowerCase();
    return products.where((p) {
      return p.name.toLowerCase().contains(q) ||
          p.description.toLowerCase().contains(q) ||
          p.brand.toLowerCase().contains(q);
    }).toList();
  }

  static Product? getById(String id) {
    try {
      return products.firstWhere((p) => p.id == id);
    } catch (_) {
      return null;
    }
  }

  static const List<Map<String, String>> banners = [
    {
      'title': 'НОВАЯ КОЛЛЕКЦИЯ\nВЕСНА 2025',
      'subtitle': 'Спорт без границ',
      'imageUrl':
          'assets/images/products/1542291026-7eec264c27ff.jpg',
      'action': 'Смотреть',
    },
    {
      'title': 'СКИДКИ\nДО 40%',
      'subtitle': 'На беговую экипировку',
      'imageUrl':
          'assets/images/products/1542291026-7eec264c27ff.jpg',
      'action': 'Купить',
    },
    {
      'title': 'ЗИМНЯЯ\nЛИНЕЙКА',
      'subtitle': 'Тепло и комфорт',
      'imageUrl':
          'assets/images/products/1542291026-7eec264c27ff.jpg',
      'action': 'Выбрать',
    },
  ];
}
