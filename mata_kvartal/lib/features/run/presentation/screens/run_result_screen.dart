import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:latlong2/latlong.dart' show LatLng;

import '../../../../core/theme/app_theme.dart';
import '../../../medals/data/medals_provider.dart';
import '../../../medals/presentation/shtamp_ceremony.dart';
import '../../../weather/data/weather_provider.dart';
import '../../data/completed_runs_provider.dart';
import '../widgets/run_share.dart';

/// Итог пробежки для церемонии (Ф1 «Праздник», утверждено 31.08.2026).
class RunResult {
  final List<LatLng> route;
  final Duration elapsed;
  final double distanceMeters;
  final int capturedZones;
  final bool capturedTerritory;
  final DateTime finishedAt;
  final String runId;

  const RunResult({
    required this.route,
    required this.elapsed,
    required this.distanceMeters,
    required this.capturedZones,
    required this.capturedTerritory,
    required this.finishedAt,
    required this.runId,
  });

  double get distanceKm => distanceMeters / 1000;

  bool get hasCapture => capturedTerritory || capturedZones > 0;

  int get quarters => math.max(capturedZones, capturedTerritory ? 1 : 0);

  /// Площадь замкнутого контура, м² (Гаусс по равнопромежуточной проекции).
  double get areaM2 {
    if (!hasCapture || route.length < 3) return 0;
    const earth = 6371000.0;
    final lat0 = route.first.latitude * math.pi / 180;
    double sum = 0;
    for (var i = 0; i < route.length; i++) {
      final a = route[i];
      final b = route[(i + 1) % route.length];
      final ax = a.longitude * math.pi / 180 * earth * math.cos(lat0);
      final ay = a.latitude * math.pi / 180 * earth;
      final bx = b.longitude * math.pi / 180 * earth * math.cos(lat0);
      final by = b.latitude * math.pi / 180 * earth;
      sum += ax * by - bx * ay;
    }
    return sum.abs() / 2;
  }

  String get elapsedFormatted {
    final h = elapsed.inHours;
    final m = elapsed.inMinutes % 60;
    final s = elapsed.inSeconds % 60;
    final mm = m.toString().padLeft(2, '0');
    final ss = s.toString().padLeft(2, '0');
    return h > 0 ? '$h:$mm:$ss' : '$mm:$ss';
  }

  String get paceFormatted {
    if (distanceKm < 0.01 || elapsed.inSeconds == 0) return '--:--';
    final pace = (elapsed.inSeconds / distanceKm).round();
    return '${(pace ~/ 60).toString().padLeft(2, '0')}:${(pace % 60).toString().padLeft(2, '0')}';
  }
}

String formatArea(double m2) {
  if (m2 >= 1000000) return '${(m2 / 1000000).toStringAsFixed(2)} км²';
  if (m2 >= 100000) return '${(m2 / 10000).toStringAsFixed(1)} га';
  final v = m2.round().toString();
  final b = StringBuffer();
  for (var i = 0; i < v.length; i++) {
    if (i > 0 && (v.length - i) % 3 == 0) b.write(' ');
    b.write(v[i]);
  }
  return '$b м²';
}

/// Церемония итогов пробежки — сцена 1 Ф1 (5.2 с, утверждённая хореография).
///
/// Правило: без захвата — без салюта. Маршрут рисуется всегда (это заслуга),
/// но вспышка по контуру и заливка квартала — только при захвате.
class RunResultScreen extends ConsumerStatefulWidget {
  final RunResult result;

  const RunResultScreen({super.key, required this.result});

  @override
  ConsumerState<RunResultScreen> createState() => _RunResultScreenState();
}

class _RunResultScreenState extends ConsumerState<RunResultScreen>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c;
  bool _hapticFlash = false;
  bool _hapticGrab = false;
  bool _medalsShown = false;

  static const _bg = Color(0xFF20252B);
  static const _light = Color(0xFFEDEFE8);
  static const _dim = Color(0xFF9AA59D);

  @override
  void initState() {
    super.initState();
    _c = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 5200),
    );
    _c.addListener(_onTick);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      if (MediaQuery.of(context).disableAnimations) {
        _c.value = 1;
        _maybeShowMedals();
      } else {
        _c.forward();
      }
    });
  }

  void _onTick() {
    final t = _c.value;
    if (widget.result.hasCapture && !_hapticFlash && t >= .46) {
      _hapticFlash = true;
      HapticFeedback.mediumImpact();
    }
    if (!_hapticGrab && t >= .58) {
      _hapticGrab = true;
      HapticFeedback.heavyImpact();
    }
    if (t >= .995) _maybeShowMedals();
  }

  /// Новые медали этой пробежки: сервер уже присвоил их лениво — забираем
  /// свежий список и чеканим каждую непоказанную («Штамп МАТА», D-64).
  /// Если бег ушёл в офлайн-очередь, медаль догонит на следующем финише.
  Future<void> _maybeShowMedals() async {
    if (_medalsShown || !mounted) return;
    _medalsShown = true;
    try {
      ref.invalidate(medalsProvider);
      final list = await ref.read(medalsProvider.future);
      final fresh = await MedalCeremonyLedger.unshown(list);
      for (final medal in fresh) {
        if (!mounted) return;
        await Future<void>.delayed(const Duration(milliseconds: 450));
        if (!mounted) return;
        await showShtampCeremony(context, medal);
      }
    } catch (_) {
      // Нет сети — церемония подождёт следующего экрана итогов.
    }
  }

  @override
  void dispose() {
    _c.removeListener(_onTick);
    _c.dispose();
    super.dispose();
  }

  void _skip() {
    if (_c.isAnimating) {
      _c.animateTo(1, duration: const Duration(milliseconds: 260));
    }
  }

  double _phase(double t, double a, double b, [Curve curve = Curves.easeOut]) {
    if (t <= a) return 0;
    if (t >= b) return 1;
    return curve.transform((t - a) / (b - a));
  }

  @override
  Widget build(BuildContext context) {
    final r = widget.result;
    final dateLabel =
        '${r.finishedAt.day.toString().padLeft(2, '0')}.${r.finishedAt.month.toString().padLeft(2, '0')} · ${r.finishedAt.hour.toString().padLeft(2, '0')}:${r.finishedAt.minute.toString().padLeft(2, '0')}';

    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) context.go('/map');
      },
      child: Scaffold(
        backgroundColor: _bg,
        body: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: _skip,
          child: AnimatedBuilder(
            animation: _c,
            builder: (context, _) {
              final t = _c.value;
              final title = _phase(t, .0, .1) * (1 - _phase(t, .74, .82) * .75);
              final draw = _phase(t, .08, .44, Curves.easeInOutCubic);
              final flash = r.hasCapture
                  ? _phase(t, .44, .48) * (1 - _phase(t, .48, .58))
                  : 0.0;
              final fill = r.hasCapture
                  ? _phase(t, .47, .59, Curves.easeOutCubic)
                  : 0.0;
              final grab = _phase(t, .57, .63, Curves.easeOutBack);
              final s1 = _phase(t, .62, .68);
              final s2 = _phase(t, .65, .71);
              final s3 = _phase(t, .68, .74);
              final panel = _phase(t, .76, .9, Curves.easeOutCubic);

              return Stack(
                fit: StackFit.expand,
                children: [
                  // Маршрут на графитовой сетке.
                  Positioned.fill(
                    bottom: 150,
                    child: CustomPaint(
                      painter: RoutePainter(
                        route: r.route,
                        progress: draw,
                        flash: flash,
                        fill: fill,
                      ),
                    ),
                  ),
                  // Заголовок.
                  Positioned(
                    top: MediaQuery.of(context).padding.top + 26,
                    left: 0,
                    right: 0,
                    child: Opacity(
                      opacity: title.clamp(0, 1),
                      child: Column(
                        children: [
                          const Text(
                            'Забег завершён',
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              fontFamily: AppTheme.fontDisplay,
                              fontSize: 21,
                              fontWeight: FontWeight.w800,
                              letterSpacing: .4,
                              color: _light,
                            ),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            dateLabel,
                            textAlign: TextAlign.center,
                            style: const TextStyle(
                              fontSize: 12.5,
                              fontWeight: FontWeight.w500,
                              color: _dim,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                  // Цифры захвата.
                  Positioned(
                    left: 0,
                    right: 0,
                    top: MediaQuery.of(context).size.height * .585 -
                        panel * 26,
                    child: Transform.scale(
                      scale: .96 + grab * .04,
                      child: Opacity(
                        opacity: grab.clamp(0, 1),
                        child: Column(
                          children: [
                            Text(
                              r.hasCapture
                                  ? '+${r.quarters} ${_qWord(r.quarters)}'
                                  : 'Пробежка засчитана',
                              textAlign: TextAlign.center,
                              style: TextStyle(
                                fontFamily: AppTheme.fontDisplay,
                                fontSize: r.hasCapture ? 38 : 27,
                                fontWeight: FontWeight.w800,
                                height: 1.05,
                                color: r.hasCapture
                                    ? const Color(0xFFDFF45F)
                                    : _light,
                              ),
                            ),
                            const SizedBox(height: 10),
                            Row(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                if (r.hasCapture) ...[
                                  Opacity(
                                    opacity: s1,
                                    child: _subStat(formatArea(r.areaM2)),
                                  ),
                                  _subDot(s2),
                                ],
                                Opacity(
                                  opacity: r.hasCapture ? s2 : s1,
                                  child: _subStat(
                                    '${r.distanceKm.toStringAsFixed(2)} км',
                                  ),
                                ),
                                _subDot(s3),
                                Opacity(
                                  opacity: s3,
                                  child: _subStat(r.elapsedFormatted),
                                ),
                              ],
                            ),
                            // «+N баллов» — как только сервер подтвердил
                            // начисление (офлайн — долетит и покажется позже).
                            Consumer(
                              builder: (context, ref, _) {
                                final award =
                                    ref.watch(lastRunPointsProvider);
                                final points =
                                    (award != null && award.runId == r.runId)
                                        ? award.points
                                        : null;
                                return AnimatedOpacity(
                                  duration:
                                      const Duration(milliseconds: 400),
                                  opacity:
                                      points != null && s3 > 0 ? 1 : 0,
                                  child: Padding(
                                    padding:
                                        const EdgeInsets.only(top: 8),
                                    child: Text(
                                      points != null
                                          ? '+$points баллов МАТА'
                                          : ' ',
                                      textAlign: TextAlign.center,
                                      style: const TextStyle(
                                        fontFamily: AppTheme.fontDisplay,
                                        fontSize: 15,
                                        fontWeight: FontWeight.w800,
                                        color: Color(0xFFDFF45F),
                                      ),
                                    ),
                                  ),
                                );
                              },
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                  // Панель итогов.
                  Positioned(
                    left: 0,
                    right: 0,
                    bottom: 0,
                    child: FractionalTranslation(
                      translation: Offset(0, 1.1 - panel * 1.1),
                      child: _StatsPanel(result: r),
                    ),
                  ),
                ],
              );
            },
          ),
        ),
      ),
    );
  }

  static String _qWord(int n) {
    final mod100 = n % 100;
    if (mod100 >= 11 && mod100 <= 14) return 'кварталов';
    return switch (n % 10) {
      1 => 'квартал',
      2 || 3 || 4 => 'квартала',
      _ => 'кварталов',
    };
  }

  Widget _subStat(String text) => Text(
    text,
    style: const TextStyle(
      fontSize: 14,
      fontWeight: FontWeight.w700,
      fontFeatures: [ui.FontFeature.tabularFigures()],
      color: Color(0xFFC9D0C6),
    ),
  );

  Widget _subDot(double o) => Opacity(
    opacity: o,
    child: const Padding(
      padding: EdgeInsets.symmetric(horizontal: 8),
      child: Text(
        '·',
        style: TextStyle(fontSize: 14, color: Color(0xFF9AA59D)),
      ),
    ),
  );
}

class _StatsPanel extends ConsumerWidget {
  final RunResult result;

  const _StatsPanel({required this.result});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    Widget stat(String value, String label) => Expanded(
      child: Column(
        children: [
          Text(
            value,
            style: const TextStyle(
              fontFamily: AppTheme.fontDisplay,
              fontSize: 21,
              fontWeight: FontWeight.w800,
              fontFeatures: [ui.FontFeature.tabularFigures()],
              color: Color(0xFF20252B),
            ),
          ),
          const SizedBox(height: 2),
          Text(
            label.toUpperCase(),
            style: const TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.w600,
              letterSpacing: .8,
              color: Color(0xFF5F665E),
            ),
          ),
        ],
      ),
    );

    return Container(
      padding: EdgeInsets.fromLTRB(
        18,
        18,
        18,
        14 + MediaQuery.of(context).padding.bottom,
      ),
      decoration: const BoxDecoration(
        color: Color(0xFFF5F4EE),
        borderRadius: BorderRadius.vertical(top: Radius.circular(22)),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              stat(result.distanceKm.toStringAsFixed(2), 'км'),
              stat(result.elapsedFormatted, 'время'),
              stat(result.paceFormatted, 'темп · мин/км'),
            ],
          ),
          const SizedBox(height: 14),
          Row(
            children: [
              Expanded(
                child: FilledButton(
                  style: FilledButton.styleFrom(
                    backgroundColor: const Color(0xFF20252B),
                    foregroundColor: const Color(0xFFDFF45F),
                    minimumSize: const Size(64, 50),
                  ),
                  onPressed: () => showRunShareSheet(
                    context,
                    RunShareData(
                      route: result.route,
                      elapsed: result.elapsed,
                      distanceMeters: result.distanceMeters,
                      capturedZones: result.capturedZones,
                      finishedAt: result.finishedAt,
                      runId: result.runId,
                      // Финиш только что — текущая погода честно равна
                      // погоде забега (у старых пробежек слот скрыт).
                      temperatureC: ref
                          .watch(weatherProvider)
                          .valueOrNull
                          ?.tempC
                          .round(),
                    ),
                  ),
                  child: const Text('Поделиться'),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: OutlinedButton(
                  style: OutlinedButton.styleFrom(
                    foregroundColor: const Color(0xFF20252B),
                    side: const BorderSide(color: Color(0xFFE0DED2)),
                    minimumSize: const Size(64, 50),
                    backgroundColor: Colors.white,
                  ),
                  onPressed: () => context.go('/map'),
                  child: const Text('На карту'),
                ),
              ),
            ],
          ),
          // Паспорт пробежки: свежая пробежка уже сохранена — первая в истории.
          Consumer(
            builder: (context, ref, _) {
              final runs = ref.watch(completedRunsProvider);
              if (runs.isEmpty) return const SizedBox.shrink();
              return TextButton(
                onPressed: () =>
                    context.push('/runs/passport', extra: runs.first),
                child: const Text(
                  'Подробнее о пробежке',
                  style: TextStyle(
                    color: Color(0xFF20252B),
                    fontWeight: FontWeight.w700,
                  ),
                ),
              );
            },
          ),
        ],
      ),
    );
  }
}

/// Маршрут: сетка города, прорисовка трека, вспышка по контуру, заливка.
class RoutePainter extends CustomPainter {
  final List<LatLng> route;
  final double progress;
  final double flash;
  final double fill;

  /// Какая доля высоты полотна отведена треку (низ — под цифры/панель).
  final double fitFactor;

  /// Отступ сверху (под заголовок церемонии).
  final double topInset;

  const RoutePainter({
    required this.route,
    required this.progress,
    this.flash = 0,
    this.fill = 0,
    this.fitFactor = .58,
    this.topInset = 70,
  });

  @override
  void paint(Canvas canvas, Size size) {
    // Сетка улиц — стенография города на графите.
    final grid = Paint()
      ..color = const Color(0xFF2C332E)
      ..strokeWidth = 1;
    const step = 34.0;
    for (var x = step; x < size.width; x += step) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), grid);
    }
    for (var y = step; y < size.height; y += step) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
    }

    if (route.length < 2) return;

    // Вписываем маршрут в холст.
    final lat0 = route.first.latitude * math.pi / 180;
    final k = math.cos(lat0);
    double minX = double.infinity, maxX = -double.infinity;
    double minY = double.infinity, maxY = -double.infinity;
    final pts = <Offset>[];
    for (final p in route) {
      final x = p.longitude * k;
      final y = -p.latitude;
      pts.add(Offset(x, y));
      minX = math.min(minX, x);
      maxX = math.max(maxX, x);
      minY = math.min(minY, y);
      maxY = math.max(maxY, y);
    }
    final w = maxX - minX, h = maxY - minY;
    const pad = 40.0;
    // Трек живёт в верхней части полотна: ниже — цифры и панель, наложений нет.
    final fitH = size.height * fitFactor;
    final scale = w == 0 && h == 0
        ? 1.0
        : math.min(
            (size.width - pad * 2) / (w == 0 ? 1e-9 : w),
            (fitH - pad * 2 - topInset) / (h == 0 ? 1e-9 : h),
          );
    final dx = (size.width - w * scale) / 2 - minX * scale;
    final dy = topInset + (fitH - topInset - h * scale) / 2 - minY * scale;

    final path = Path();
    for (var i = 0; i < pts.length; i++) {
      final o = Offset(pts[i].dx * scale + dx, pts[i].dy * scale + dy);
      if (i == 0) {
        path.moveTo(o.dx, o.dy);
      } else {
        path.lineTo(o.dx, o.dy);
      }
    }

    // Заливка захваченного контура.
    if (fill > 0) {
      final closed = Path.from(path)..close();
      canvas.drawPath(
        closed,
        Paint()
          ..color = const Color(0xFFDFF45F)
              .withValues(alpha: .88 * fill * .38),
      );
    }

    // Частичная прорисовка трека.
    final metrics = path.computeMetrics().toList();
    final total = metrics.fold<double>(0, (a, m) => a + m.length);
    var remain = total * progress;
    final drawn = Path();
    Offset? head;
    for (final m in metrics) {
      if (remain <= 0) break;
      final len = math.min(remain, m.length);
      drawn.addPath(m.extractPath(0, len), Offset.zero);
      final tangent = m.getTangentForOffset(len);
      if (tangent != null) head = tangent.position;
      remain -= len;
    }

    // Вспышка по контуру — только по форме маршрута, никаких кругов.
    if (flash > 0) {
      canvas.drawPath(
        drawn,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 11
          ..strokeCap = StrokeCap.round
          ..strokeJoin = StrokeJoin.round
          ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 7)
          ..color = const Color(0xFFDFF45F).withValues(alpha: .85 * flash),
      );
    }

    canvas.drawPath(
      drawn,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 5
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round
        ..color = const Color(0xFFEDEFE8),
    );

    // Бегун ведёт линию.
    if (head != null && progress > 0 && progress < 1) {
      canvas.drawCircle(
        head,
        7,
        Paint()..color = const Color(0xFFDFF45F),
      );
      canvas.drawCircle(
        head,
        7,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2
          ..color = const Color(0xFF20252B),
      );
    }

    // Точка старта.
    if (progress > 0) {
      final start = pts.first;
      canvas.drawCircle(
        Offset(start.dx * scale + dx, start.dy * scale + dy),
        4,
        Paint()..color = const Color(0xFFEDEFE8),
      );
    }
  }

  @override
  bool shouldRepaint(RoutePainter old) =>
      old.progress != progress ||
      old.flash != flash ||
      old.fill != fill ||
      old.route != route;
}
