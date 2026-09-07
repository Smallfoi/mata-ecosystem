import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/features/medals/data/medal_defs.dart';
import 'package:kvartal_app/features/medals/data/medals_provider.dart';
import 'package:kvartal_app/features/medals/presentation/emblem_motion.dart';

/// Инструмент стоп-кадров живых эмблем (аналог ?t= для анимаций): рендерит
/// композит база+слои в PNG на нескольких точках цикла. Запуск руками:
///   flutter test test/tool_render_emblem_frames_test.dart
/// Кадры пишутся в EMBLEM_FRAMES_DIR (иначе тест просто проверяет сборку
/// композита без падений — быстрый смоук на каждом прогоне CI).
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  final outDir = Platform.environment['EMBLEM_FRAMES_DIR'];

  for (final id in emblemMotion.keys) {
    testWidgets('композит $id собирается (и кадры при EMBLEM_FRAMES_DIR)',
        (tester) async {
      final medal = MedalFull(
        medalById(id),
        MedalState(id: id, available: true, earnedAtMs: 1757000000000),
      );
      final key = GlobalKey();
      await tester.pumpWidget(
        MaterialApp(
          home: ColoredBox(
            color: const Color(0xFF0F1216),
            child: Center(
              child: RepaintBoundary(
                key: key,
                child: LiveMedalImage(medal: medal, size: 232),
              ),
            ),
          ),
        ),
      );
      // Дать WebP-ассетам декодироваться (реальный async — только в runAsync).
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 300)),
      );
      await tester.pump(const Duration(milliseconds: 20));
      final period = emblemMotion[id]!
          .map((l) => l.periodMs)
          .reduce((a, b) => a > b ? a : b);
      var last = 0.0;
      for (final f in [0.0, .07, .25, .45, .65, .9]) {
        await tester
            .pump(Duration(milliseconds: (period * (f - last)).round()));
        last = f;
        if (outDir == null) continue;
        await tester.runAsync(() async {
          final boundary =
              key.currentContext!.findRenderObject() as RenderRepaintBoundary;
          final img = await boundary.toImage(pixelRatio: 2);
          final bytes = await img.toByteData(format: ui.ImageByteFormat.png);
          final file = File(
              '$outDir/${id}_${(f * 100).round().toString().padLeft(2, '0')}.png');
          file.parent.createSync(recursive: true);
          file.writeAsBytesSync(bytes!.buffer.asUint8List());
        });
      }
      expect(tester.takeException(), isNull);
    });
  }
}
