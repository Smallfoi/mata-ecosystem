/// Разметка снимка витрины (владелец 27.11.2026): где на кадре товар, цвет фона
/// и пропорции. Сервер меряет снимок один раз при загрузке
/// (`productmedia.images.measure`), а сайт и приложение по ней ставят товар
/// ЦЕЛИКОМ в центр рамки, с полями цвета фона — вместо обрезки «по центру»,
/// которая резала подошвы ANTA, головы моделей STAW и края очков.
///
/// Тот же расчёт — на сайте (`САЙТ МАТА/script.js`, fitLayout): меняешь одно —
/// меняй и другое.
class PhotoFit {
  /// Рамка товара долями кадра: лево, верх, право, низ.
  final double left, top, right, bottom;

  /// Цвет фона снимка, 0xAARRGGBB.
  final int bg;

  /// Пропорции снимка: ширина / высота.
  final double ar;

  const PhotoFit({
    required this.left,
    required this.top,
    required this.right,
    required this.bottom,
    required this.bg,
    required this.ar,
  });

  /// Поле вокруг товара, доля рамки.
  static const double pad = 0.07;

  /// Крупнее не тянем: снимки ~1000 px, дальше мыло.
  static const double maxScale = 2.5;

  /// `{"box": [l, t, r, b], "bg": "#rrggbb", "ar": 0.75}`; не размечен — null.
  static PhotoFit? fromJson(Object? j) {
    if (j is! Map) return null;
    final ar = (j['ar'] as num?)?.toDouble();
    final box = j['box'];
    if (ar == null || ar <= 0 || box is! List || box.length != 4) return null;
    final b = box.map((v) => (v as num?)?.toDouble() ?? 0).toList();
    final hex = (j['bg'] ?? '').toString().replaceFirst('#', '');
    final rgb = hex.length == 6 ? int.tryParse(hex, radix: 16) : null;
    return PhotoFit(
      left: b[0], top: b[1], right: b[2], bottom: b[3],
      bg: 0xFF000000 | (rgb ?? 0xF3F1EC),
      ar: ar,
    );
  }

  Map<String, dynamic> toJson() => {
        'box': [left, top, right, bottom],
        'bg': '#${(bg & 0xFFFFFF).toRadixString(16).padLeft(6, '0')}',
        'ar': ar,
      };

  /// Где лежит снимок в рамке [w]×[h] (в тех же единицах): x, y, ширина, высота.
  ///
  /// Товар обрезан краем самого снимка (модель по пояс) — этим краем он встаёт
  /// к краю рамки, а не висит посередине с полем под обрезом.
  ({double x, double y, double w, double h}) place(double w, double h) {
    final f = w / h;
    final eL = left <= 0.01, eT = top <= 0.01, eR = right >= 0.99, eB = bottom >= 0.99;
    final aw = 1 - (eL ? 0 : pad) - (eR ? 0 : pad);
    final ah = 1 - (eT ? 0 : pad) - (eB ? 0 : pad);
    var k = aw / _atLeast(right - left);
    final kh = ah * ar / (_atLeast(bottom - top) * f);
    if (kh < k) k = kh;
    if (maxScale < k) k = maxScale;
    final hk = k * f / ar;
    final x = eL && !eR ? -left * k : eR && !eL ? 1 - right * k : 0.5 - (left + right) / 2 * k;
    final y = eT && !eB ? -top * hk : eB && !eT ? 1 - bottom * hk : 0.5 - (top + bottom) / 2 * hk;
    return (x: x * w, y: y * h, w: k * w, h: hk * h);
  }

  static double _atLeast(double v) => v < 0.01 ? 0.01 : v;
}
