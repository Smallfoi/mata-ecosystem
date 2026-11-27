import 'package:flutter_test/flutter_test.dart';
import 'package:sport_store/models/photo_fit.dart';
import 'package:sport_store/models/product.dart';

void main() {
  test('кроссовок в нижней трети вытянутого кадра встаёт в центр квадрата', () {
    // Как у ANTA: кадр 2:3, товар занимает 8–94% по ширине и 51–80% по высоте.
    final fit = PhotoFit.fromJson({
      'box': [0.08, 0.51, 0.94, 0.80],
      'bg': '#dfdbd8',
      'ar': 0.6675,
    })!;
    expect(fit.bg, 0xFFDFDBD8);
    final r = fit.place(100, 100);
    final shoeLeft = r.x + 0.08 * r.w, shoeRight = r.x + 0.94 * r.w;
    final shoeTop = r.y + 0.51 * r.h, shoeBottom = r.y + 0.80 * r.h;
    expect(shoeLeft, closeTo(7, 0.5));            // поле 7% слева
    expect(100 - shoeRight, closeTo(7, 0.5));     // и справа
    expect((shoeTop + shoeBottom) / 2, closeTo(50, 0.5)); // по центру высоты
  });

  test('модель, обрезанная низом кадра, стоит на нижнем краю рамки', () {
    final fit = PhotoFit.fromJson({
      'box': [0.25, 0.07, 0.77, 1.0],
      'bg': '#f0ece4',
      'ar': 0.75,
    })!;
    final r = fit.place(100, 100);
    expect(r.y + r.h, closeTo(100, 0.01));
    expect(r.y + 0.07 * r.h, greaterThanOrEqualTo(0)); // голова в кадре
  });

  test('без разметки — null, снимок показывается как раньше', () {
    expect(PhotoFit.fromJson(null), isNull);
    expect(PhotoFit.fromJson(<String, dynamic>{}), isNull);
    expect(PhotoFit.fromJson({'box': [0, 0, 1, 1], 'ar': 0}), isNull);
  });

  test('разметка обложки приходит из карточки модели', () {
    final p = Product.fromModelCard({
      'key': 'k',
      'name': 'n',
      'cardUrl': 'https://x/c.webp',
      'cardFit': {'box': [0.1, 0.1, 0.9, 0.9], 'bg': '#ffffff', 'ar': 1},
      'colors': [
        {
          'name': 'ЧЕРНЫЙ',
          'photos': [
            {'url': 'https://x/a.webp', 'fit': {'box': [0.2, 0.2, 0.8, 0.8], 'bg': '#eeeeee', 'ar': 1}}
          ],
          'sizes': [],
        }
      ],
    });
    expect(p.coverCardFit?.left, 0.1);
    expect(p.photosFor('ЧЕРНЫЙ').first.fit?.bg, 0xFFEEEEEE);
  });
}
