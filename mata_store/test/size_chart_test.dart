import 'package:flutter_test/flutter_test.dart';
import 'package:sport_store/models/product.dart';

/// Таблица размеров и товары «без размера» в карточке модели (аудит сайта, пункт 9).
void main() {
  test('sizeChart карточки → таблицы размеров', () {
    final p = Product.fromModelCard({
      'key': '812625546',
      'name': 'ANTA WALK 3.0',
      'price': 9000,
      'sizes': ['42'],
      'sizeChart': {
        'tables': [
          {
            'title': 'ANTA · мужская обувь',
            'columns': ['EU', 'RUS', 'US', 'UK', 'Длина стопы, см', 'Обхват стопы, мм'],
            'rows': [
              ['42', '41', '8,5', '7,5', '26,5', '248'],
            ],
            'match': 0,
            'note': 'справочно',
          }
        ]
      },
    });
    expect(p.sizeTables, hasLength(1));
    expect(p.sizeTables.first.columns.first, 'EU');
    expect(p.sizeTables.first.rows.first[4], '26,5');
    expect(Product.fromJson(p.toJson()).sizeTables.first.title, 'ANTA · мужская обувь');
  });

  test('нет таблицы — пустой список', () {
    final p = Product.fromModelCard({'key': 'g', 'name': 'Гель', 'price': 300, 'sizeChart': null});
    expect(p.sizeTables, isEmpty);
  });

  test('«Б/Р» — не размер: выбирать нечего, позиция берётся по цвету', () {
    final p = Product.fromModelCard({
      'key': '192518142',
      'name': 'Сумка ANTA SKATE',
      'price': 2500,
      'sizes': ['Б/Р'],
      'colors': [
        {
          'name': 'Черный',
          'sizes': [
            {'size': 'Б/Р', 'productId': 'p1', 'price': 2500, 'inStock': true}
          ]
        }
      ],
    });
    expect(p.sizes, isEmpty);
    expect(p.variantFor('', 'Черный')?.productId, 'p1');
    expect(isOneSize('F'), isTrue);
    expect(isOneSize('XL'), isFalse);
  });
}
