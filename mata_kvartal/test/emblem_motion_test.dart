import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/features/medals/data/medal_defs.dart';
import 'package:kvartal_app/features/medals/presentation/emblem_motion.dart';

/// Спецификации живых эмблем: каждая ссылается на существующую медаль,
/// каждый слой имеет валидный цикл и СВОИ файлы базы+слоёв в ассетах —
/// иначе зал показал бы битую медаль вместо живой.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('каждая спецификация — про существующую медаль', () {
    final ids = kMedals.map((d) => d.id).toSet();
    for (final id in emblemMotion.keys) {
      expect(ids.contains(id), isTrue, reason: 'нет медали $id');
    }
  });

  test('ключи каждого слоя — отсортированный цикл 0..1', () {
    emblemMotion.forEach((id, layers) {
      expect(layers, isNotEmpty, reason: id);
      for (final l in layers) {
        expect(l.keys.length >= 2, isTrue, reason: '$id/${l.part}');
        expect(l.keys.first.t, 0, reason: '$id/${l.part}: цикл начинается с 0');
        expect(l.keys.last.t, 1, reason: '$id/${l.part}: цикл кончается на 1');
        for (var i = 1; i < l.keys.length; i++) {
          expect(l.keys[i].t >= l.keys[i - 1].t, isTrue,
              reason: '$id/${l.part}: ключи не по порядку');
        }
        expect(l.periodMs > 0, isTrue, reason: '$id/${l.part}');
      }
    });
  });

  test('порядок частей согласован со слоями', () {
    for (final id in emblemMotion.keys) {
      final parts = emblemParts[id];
      expect(parts, isNotNull, reason: 'нет порядка частей для $id');
      for (final l in emblemMotion[id]!) {
        expect(parts!.contains(l.part), isTrue,
            reason: '$id: слой ${l.part} не в порядке частей');
      }
    }
    expect(emblemParts.keys.toSet(), emblemMotion.keys.toSet());
  });

  test('все части каждой живой медали лежат в ассетах', () async {
    for (final entry in emblemParts.entries) {
      for (final part in entry.value) {
        final path = 'assets/medals/anim/${entry.key}__$part.webp';
        final data = await rootBundle.load(path);
        expect(data.lengthInBytes > 500, isTrue, reason: '$path пустой');
      }
    }
  });
}
