// Инструмент визуальной проверки «Квартал 2.0» (приём стоп-кадров, как ?t= в
// дизайн-проектах): рендерит ключевые кадры церемоний Ф1, welcome Ф3,
// шаринг-карточку и экран «Тема» в PNG (build/frames/). Сетевых вызовов нет.
// Смотреть: `flutter test test/tool_render_phase_frames_test.dart`.
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:latlong2/latlong.dart' show LatLng;
import 'package:shared_preferences/shared_preferences.dart';

import 'package:kvartal_app/core/theme/app_colors.dart';
import 'package:kvartal_app/core/theme/app_theme.dart';
import 'package:kvartal_app/features/auth/presentation/screens/welcome_screen.dart';
import 'package:kvartal_app/features/medals/data/medal_defs.dart';
import 'package:kvartal_app/features/medals/data/medals_provider.dart';
import 'package:kvartal_app/features/medals/presentation/medal_widgets.dart';
import 'package:kvartal_app/features/medals/presentation/shtamp_ceremony.dart';
import 'package:kvartal_app/features/profile/presentation/screens/theme_screen.dart';
import 'package:kvartal_app/features/run/presentation/screens/run_result_screen.dart';
import 'package:kvartal_app/features/run/presentation/widgets/run_share.dart';

Future<void> _loadFonts() async {
  final cupertino = FontLoader('packages/cupertino_icons/CupertinoIcons');
  cupertino.addFont(
    rootBundle.load('packages/cupertino_icons/assets/CupertinoIcons.ttf'),
  );
  await cupertino.load();
  for (final family in ['Manrope', 'Inter']) {
    final loader = FontLoader(family);
    for (final w in ['400', '500', '600', '700', '800']) {
      if (family == 'Manrope' && w == '400') continue;
      loader.addFont(rootBundle.load('assets/fonts/$family-$w.ttf'));
    }
    await loader.load();
  }
  // Unbounded — имена медалей и цифры гравировки «Штампа МАТА».
  final unbounded = FontLoader('Unbounded');
  for (final w in ['600', '700', '800']) {
    unbounded.addFont(rootBundle.load('assets/fonts/Unbounded-$w.ttf'));
  }
  await unbounded.load();
}

RunResult _sampleResult({required bool captured}) {
  // Квадратный круг ~500 м в центре Якутска с лёгкой «живостью» линий.
  const lat0 = 62.0282;
  const lng0 = 129.7325;
  final pts = <LatLng>[];
  const n = 14;
  for (var side = 0; side < 4; side++) {
    for (var i = 0; i < n; i++) {
      final t = i / n;
      final jitter = ((i * 7 + side * 13) % 5 - 2) * 0.000012;
      switch (side) {
        case 0:
          pts.add(LatLng(lat0 + jitter, lng0 + 0.0052 * t));
        case 1:
          pts.add(LatLng(lat0 + 0.0026 * t + jitter, lng0 + 0.0052));
        case 2:
          pts.add(LatLng(lat0 + 0.0026 + jitter, lng0 + 0.0052 * (1 - t)));
        case 3:
          pts.add(LatLng(lat0 + 0.0026 * (1 - t) + jitter, lng0));
      }
    }
  }
  pts.add(pts.first);
  return RunResult(
    route: pts,
    elapsed: const Duration(minutes: 24, seconds: 37),
    distanceMeters: 4180,
    capturedZones: captured ? 3 : 0,
    capturedTerritory: captured,
    finishedAt: DateTime(2026, 8, 31, 21, 42),
    runId: 'frame-tool',
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUpAll(() async {
    await _loadFonts();
    SharedPreferences.setMockInitialValues({});
  });

  Future<void> capture(WidgetTester tester, GlobalKey key, String name) async {
    await tester.runAsync(() async {
      final boundary =
          key.currentContext!.findRenderObject() as RenderRepaintBoundary;
      final image = await boundary.toImage(pixelRatio: 2);
      final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
      final out = File('build/frames/$name.png');
      out.parent.createSync(recursive: true);
      out.writeAsBytesSync(bytes!.buffer.asUint8List());
    });
  }

  Widget shell(GlobalKey key, Widget child) => ProviderScope(
    child: MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: AppTheme.current(),
      home: RepaintBoundary(key: key, child: child),
    ),
  );

  void phoneSize(WidgetTester tester) {
    tester.view.physicalSize = const Size(390 * 3, 844 * 3);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
  }

  testWidgets('run result ceremony frames (captured)', (tester) async {
    phoneSize(tester);
    AppColors.isGraphite = true;
    final key = GlobalKey();
    await tester.pumpWidget(
      shell(key, RunResultScreen(result: _sampleResult(captured: true))),
    );
    await tester.pump(const Duration(milliseconds: 50));
    var elapsed = 50;
    for (final (ms, name) in [
      (1500, 'f1_run_draw'),
      (2450, 'f1_run_flash'),
      (3100, 'f1_run_fill'),
      (3600, 'f1_run_numbers'),
      (5100, 'f1_run_panel'),
    ]) {
      await tester.pump(Duration(milliseconds: ms - elapsed));
      elapsed = ms;
      await capture(tester, key, name);
    }
    // Дожимаем таймлайн, даём цепочке медалей отработать и закрываем её.
    await tester.pump(const Duration(milliseconds: 700));
    await tester.pump(const Duration(milliseconds: 600));
    await tester.pump(const Duration(seconds: 6));
    if (tester.any(find.text('Забрать'))) {
      await tester.tap(find.text('Забрать'));
      await tester.pump(const Duration(milliseconds: 400));
    }
    await tester.pump(const Duration(milliseconds: 600));
  });

  testWidgets('run result quiet frame (no capture)', (tester) async {
    phoneSize(tester);
    AppColors.isGraphite = true;
    final key = GlobalKey();
    await tester.pumpWidget(
      shell(key, RunResultScreen(result: _sampleResult(captured: false))),
    );
    await tester.pump(const Duration(milliseconds: 5100));
    await capture(tester, key, 'f1_run_quiet');
    await tester.pump(const Duration(milliseconds: 200));
    await tester.pump(const Duration(milliseconds: 600));
    await tester.pump(const Duration(seconds: 6));
    if (tester.any(find.text('Забрать'))) {
      await tester.tap(find.text('Забрать'));
      await tester.pump(const Duration(milliseconds: 400));
    }
    await tester.pump(const Duration(milliseconds: 600));
  });

  testWidgets('medal ceremony frames', (tester) async {
    phoneSize(tester);
    AppColors.isGraphite = true;
    final key = GlobalKey();
    late BuildContext ctx;
    await tester.pumpWidget(
      ProviderScope(
        child: RepaintBoundary(
          key: key,
          child: MaterialApp(
            debugShowCheckedModeBanner: false,
            theme: AppTheme.current(),
            home: Builder(
              builder: (c) {
                ctx = c;
                return const Scaffold(
                  backgroundColor: Color(0xFF20252B),
                  body: SizedBox.expand(),
                );
              },
            ),
          ),
        ),
      ),
    );
    // Чеканка «Штампа МАТА»: медаль вбивается, блик, строки поднимаются.
    final medal = MedalFull(
      medalById('d_first_run'),
      MedalState(
        id: 'd_first_run',
        available: true,
        earnedAtMs: DateTime.now().millisecondsSinceEpoch,
        engraving: (v: '5,2 КМ', u: 'ПЕРВЫЙ БЕГ', sub: '01.09.2026'),
      ),
    );
    // ignore: unawaited_futures
    showShtampCeremony(ctx, medal);
    await tester.pump(const Duration(milliseconds: 250));
    var elapsed = 0;
    for (final (ms, name) in [
      (300, 'f1_medal_strike'),
      (700, 'f1_medal_set'),
      (1100, 'f1_medal_sheen'),
      (1800, 'f1_medal_final'),
    ]) {
      await tester.pump(Duration(milliseconds: ms - elapsed));
      elapsed = ms;
      await capture(tester, key, name);
    }
    await tester.pump(const Duration(milliseconds: 400));
    if (tester.any(find.text('Дальше'))) {
      await tester.tap(find.text('Дальше'));
      await tester.pump(const Duration(milliseconds: 400));
    }
  });

  testWidgets('medal reverse engraving frame', (tester) async {
    phoneSize(tester);
    AppColors.isGraphite = true;
    final key = GlobalKey();
    await tester.pumpWidget(
      RepaintBoundary(
        key: key,
        child: MaterialApp(
          debugShowCheckedModeBanner: false,
          theme: AppTheme.current(),
          home: Scaffold(
            backgroundColor: const Color(0xFF20252B),
            body: Center(
              child: MedalReverse(
                def: medalById('t_zones_100'),
                engraving: (v: '127', u: 'ЗОН · ПИК', sub: '12.05.2026 · ЯКУТСК'),
                size: 300,
              ),
            ),
          ),
        ),
      ),
    );
    // Дать декодеру картинки дорисовать реверс.
    await tester.runAsync(() => Future<void>.delayed(
        const Duration(milliseconds: 300)));
    await tester.pump(const Duration(milliseconds: 100));
    await capture(tester, key, 'f1_medal_reverse');
  });

  testWidgets('welcome pages frames', (tester) async {
    phoneSize(tester);
    final key = GlobalKey();
    await tester.pumpWidget(shell(key, const WelcomeScreen()));
    await tester.pump(const Duration(milliseconds: 900));
    await capture(tester, key, 'f3_welcome_1');
    for (var i = 2; i <= 4; i++) {
      await tester.tap(find.text(i == 4 ? 'Дальше' : 'Дальше'));
      await tester.pump(const Duration(milliseconds: 400));
      await tester.pump(const Duration(milliseconds: 500));
      await capture(tester, key, 'f3_welcome_$i');
    }
  });

  testWidgets('share card frame', (tester) async {
    phoneSize(tester);
    AppColors.isGraphite = true;
    final key = GlobalKey();
    await tester.pumpWidget(
      shell(
        key,
        Scaffold(
          backgroundColor: const Color(0xFFF5F4EE),
          body: Center(
            child: Builder(builder: (context) {
              final r = _sampleResult(captured: true);
              return RunStoryCard(
                data: RunShareData(
                  route: r.route,
                  elapsed: r.elapsed,
                  distanceMeters: r.distanceMeters,
                  capturedZones: r.capturedZones,
                  finishedAt: r.finishedAt,
                ),
                runner: 'Михаил Татаринов',
                city: 'Якутск',
              );
            }),
          ),
        ),
      ),
    );
    await tester.pump(const Duration(milliseconds: 300));
    await capture(tester, key, 'f1_share_card');
  });

  testWidgets('theme screen frames (both interiors)', (tester) async {
    phoneSize(tester);
    for (final graphite in [true, false]) {
      AppColors.isGraphite = graphite;
      final key = GlobalKey();
      await tester.pumpWidget(shell(key, const ThemeScreen()));
      await tester.pump(const Duration(milliseconds: 300));
      await capture(
        tester,
        key,
        graphite ? 'f8_theme_graphite' : 'f8_theme_light',
      );
    }
    AppColors.isGraphite = true;
  });
}
