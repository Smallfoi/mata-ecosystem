import 'package:flutter_test/flutter_test.dart';
import 'package:sport_store/models/product.dart';

/// Витрина показывает МОДЕЛЬ, склад ведёт размеры отдельными карточками (D-94).
/// Главное здесь: в корзину обязана уйти складская позиция выбранного
/// сочетания, а чего нет на складе — не должно выглядеть доступным.
void main() {
  Map<String, dynamic> card({List<Map<String, dynamic>>? colors}) => {
        'key': 'BMAI EXPEDITION',
        'name': 'Кроссовки BMAI Expedition',
        'brand': 'BMAI',
        'categoryId': 'shoes',
        'price': 4490,
        'imageUrl': 'https://example.org/a.webp',
        'sizes': ['41', '42'],
        'rating': 4.5,
        'reviewCount': 3,
        'colors': colors ??
            [
              {
                'name': 'ЧЁРНЫЙ',
                'sizes': [
                  {'size': '41', 'productId': 'p1', 'price': 4490, 'inStock': true},
                  {'size': '42', 'productId': 'p2', 'price': 4490, 'inStock': false},
                ],
              },
              {
                'name': 'МЯТНЫЙ',
                'sizes': [
                  {'size': '42', 'productId': 'p3', 'price': 4990, 'inStock': true},
                ],
              },
            ],
      };

  group('Product.fromModelCard', () {
    test('собирает один товар из всех цветов и размеров', () {
      final p = Product.fromModelCard(card());
      expect(p.id, 'BMAI EXPEDITION');
      expect(p.sizes, ['41', '42']);
      expect(p.colors, ['ЧЁРНЫЙ', 'МЯТНЫЙ']);
      expect(p.variants.length, 3);
      expect(p.rating, 4.5);
      expect(p.reviewCount, 3);
    });

    test('в заказ уходит позиция склада выбранного сочетания', () {
      final p = Product.fromModelCard(card());
      expect(p.variantFor('41', 'ЧЁРНЫЙ')!.productId, 'p1');
      expect(p.variantFor('42', 'МЯТНЫЙ')!.productId, 'p3');
      expect(p.variantFor('41', 'МЯТНЫЙ'), isNull,
          reason: 'такого сочетания на складе нет');
    });

    test('цена берётся у варианта, а не у карточки', () {
      final p = Product.fromModelCard(card());
      expect(p.price, 4490, reason: 'на карточке — самая дешёвая');
      expect(p.variantFor('42', 'МЯТНЫЙ')!.price, 4990);
    });

    test('размер недоступен в том цвете, где его нет', () {
      final p = Product.fromModelCard(card());
      expect(p.hasSizeInColor('41', 'ЧЁРНЫЙ'), isTrue);
      expect(p.hasSizeInColor('42', 'ЧЁРНЫЙ'), isFalse, reason: 'распродан');
      expect(p.hasSizeInColor('41', 'МЯТНЫЙ'), isFalse, reason: 'нет такой позиции');
    });

    test('до выбора цвета размеры не гасим', () {
      final p = Product.fromModelCard(card());
      for (final s in p.sizes) {
        expect(p.hasSizeInColor(s, null), isTrue, reason: 'размер $s спрятали зря');
      }
    });

    test('цвет без единого доступного размера недоступен', () {
      final p = Product.fromModelCard(card(colors: [
        {
          'name': 'ЧЁРНЫЙ',
          'sizes': [
            {'size': '41', 'productId': 'p1', 'price': 4490, 'inStock': false},
          ],
        },
        {
          'name': 'МЯТНЫЙ',
          'sizes': [
            {'size': '41', 'productId': 'p2', 'price': 4490, 'inStock': true},
          ],
        },
      ]));
      expect(p.hasColor('ЧЁРНЫЙ'), isFalse);
      expect(p.hasColor('МЯТНЫЙ'), isTrue);
    });

    test('копия с позицией склада сохраняет остальное', () {
      final p = Product.fromModelCard(card());
      final v = p.variantFor('42', 'МЯТНЫЙ')!;
      final ordered = p.copyWith(id: v.productId, price: v.price);
      expect(ordered.id, 'p3');
      expect(ordered.price, 4990);
      expect(ordered.name, p.name);
      expect(ordered.imageUrls, p.imageUrls);
    });

    test('переживает пустую карточку без цветов', () {
      final p = Product.fromModelCard({'key': 'k', 'name': 'Товар', 'price': 100});
      expect(p.variants, isEmpty);
      expect(p.colors, isEmpty);
      // Без вариантов работаем как раньше: размеры не прячем.
      expect(p.hasSizeInColor('42', null), isTrue);
      expect(p.hasColor('ЧЁРНЫЙ'), isTrue);
    });
  });
}
