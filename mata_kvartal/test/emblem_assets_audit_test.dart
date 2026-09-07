import 'dart:convert';
import 'dart:ui' as ui;

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

/// Страж пустых слоёв (баг владельца 05.09: у «5 км» пропала разметка —
/// слой внутри SVG-клипа экспортировался нулевым). Каждый ассет живых
/// эмблем обязан содержать видимые пиксели — пустой слой = битая медаль.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('каждый слой/сегмент живых эмблем содержит пиксели', () async {
    final manifest = json.decode(
      await rootBundle.loadString('AssetManifest.json'),
    ) as Map<String, dynamic>;
    final assets = manifest.keys
        .where((k) => k.startsWith('assets/medals/anim/'))
        .toList()
      ..sort();
    expect(assets, isNotEmpty);

    final empty = <String>[];
    for (final path in assets) {
      final bytes = await rootBundle.load(path);
      final codec = await ui.instantiateImageCodec(
        bytes.buffer.asUint8List(),
        // 384 — компромисс: крошечные элементы (огонёк гирлянды, окно
        // города) остаются видимыми паре пикселей, декод быстрый.
        targetWidth: 384,
        targetHeight: 384,
      );
      final image = (await codec.getNextFrame()).image;
      final data = await image.toByteData(format: ui.ImageByteFormat.rawRgba);
      var opaque = 0;
      final list = data!.buffer.asUint8List();
      for (var i = 3; i < list.length; i += 4) {
        if (list[i] > 8) opaque++;
      }
      image.dispose();
      if (opaque < 2) empty.add('$path ($opaque px)');
    }
    expect(empty, isEmpty,
        reason: 'ПУСТЫЕ слои — медаль потеряет часть рисунка:\n'
            '${empty.join('\n')}');
  });
}
