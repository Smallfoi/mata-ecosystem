import 'dart:io';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart' show Distance, LatLng;
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import '../../../../core/theme/app_theme.dart';
import '../../../auth/data/auth_provider.dart';
import '../../../medals/data/medal_defs.dart';
import '../../../medals/data/medals_provider.dart';
import '../../data/completed_runs_provider.dart' show lastRunPointsProvider;
import '../../../medals/presentation/medal_share.dart'
    show BrandMark, InstagramButtonLabel, StickerHint, saveShareImageToGallery;

/// Шаринг пробежки «Росчерк» (дизайн утверждён 05.09.2026; карточка v2 —
/// эталон «Выше Стравы», утверждён 06.09.2026): маршрут — герой на сетке
/// города, росчерк с градиентом и км-точками, при захвате — заголовок вызова
/// и гекс-контуры кварталов, медаль забега — настоящим штампом; прозрачный
/// стикер — только трек и цифры на собственное фото бегуна. Механика Инсты
/// общая с медалями (тот же канал).
const _instaChannel = MethodChannel('kvartal/instagram_share');

const _bg = Color(0xFF12161B);
const _panel = Color(0xFF1B2129);
const _ink = Color(0xFFEDEFE8);
const _muted = Color(0xFF97A0A6);
const _lime = Color(0xFFDFF45F);
const _cyan = Color(0xFF6FD3E0);

// Meta App ID — публичный (см. medal_share.dart, там же грабля про пустой
// --dart-define, перекрывающий defaultValue). Дубль, чтобы не тянуть медали
// в модуль пробежек.
const _envMetaAppId = String.fromEnvironment('META_APP_ID');
const _metaAppId =
    _envMetaAppId == '' ? '1058928553560826' : _envMetaAppId;

/// Данные для карточки: у пробежки может не быть баллов или температуры —
/// карточка строится из того, что есть, пустые слоты честно скрыты.
class RunShareData {
  final List<LatLng> route;
  final Duration elapsed;
  final double distanceMeters;
  final int capturedZones;
  final DateTime finishedAt;

  /// id забега — по нему шит находит баллы последней синкнутой пробежки.
  final String? runId;

  /// Температура на старте (климат-козырь «бежал в −40»). Сейчас её передаёт
  /// только экран финиша (текущая погода ≈ погода забега); у старых пробежек
  /// поля нет — слот скрыт, врать карточка не будет.
  final int? temperatureC;

  const RunShareData({
    required this.route,
    required this.elapsed,
    required this.distanceMeters,
    required this.capturedZones,
    required this.finishedAt,
    this.runId,
    this.temperatureC,
  });

  double get distanceKm => distanceMeters / 1000;
}

Future<void> showRunShareSheet(BuildContext context, RunShareData data) {
  return showModalBottomSheet<void>(
    context: context,
    backgroundColor: const Color(0xFF161B21),
    isScrollControlled: true,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(22)),
    ),
    builder: (_) => _RunShareSheet(data: data),
  );
}

class _RunShareSheet extends ConsumerStatefulWidget {
  final RunShareData data;
  const _RunShareSheet({required this.data});

  @override
  ConsumerState<_RunShareSheet> createState() => _RunShareSheetState();
}

class _RunShareSheetState extends ConsumerState<_RunShareSheet> {
  final _boundaryKey = GlobalKey();
  bool _stickerMode = false;
  bool _showStats = true; // на стикере цифры можно скрыть — чистый росчерк
  bool _busy = false;

  @override
  Widget build(BuildContext context) {
    final runner = ref.watch(authProvider).user?.name ?? 'Бегун КВАРТАЛ';
    final city = ref.watch(authProvider).user?.city;
    // Медали, взятые в этом забеге, — то же окно, что в Паспорте:
    // [старт−1 мин, финиш+10 мин] (сервер судит при синке после финиша).
    final d = widget.data;
    final started = d.finishedAt.subtract(d.elapsed);
    final medals = ref.watch(medalsProvider).valueOrNull ?? const <MedalFull>[];
    final awards = [
      for (final m in medals)
        if (m.state.earnedAtMs != null &&
            m.state.earnedAtMs! >=
                started
                    .subtract(const Duration(minutes: 1))
                    .millisecondsSinceEpoch &&
            m.state.earnedAtMs! <=
                d.finishedAt
                    .add(const Duration(minutes: 10))
                    .millisecondsSinceEpoch)
          m,
    ];
    final lastPoints = ref.watch(lastRunPointsProvider);
    final points = lastPoints != null && lastPoints.runId == d.runId
        ? lastPoints.points
        : null;
    final preview = _stickerMode
        ? RunSticker(data: widget.data, showStats: _showStats)
        : RunStoryCard(
            data: widget.data,
            runner: runner,
            city: city,
            medal: awards.isEmpty ? null : awards.first,
            extraAwards: awards.isEmpty ? 0 : awards.length - 1,
            points: points,
          );

    return SafeArea(
      // Скролл — страховка от переполнения на невысоких экранах: контент
      // шита выше 700 логических пикселей (правило «никаких наложений»).
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              'Поделиться пробежкой',
              style: TextStyle(
                fontFamily: AppTheme.fontDisplay,
                fontSize: 17,
                fontWeight: FontWeight.w800,
                color: _ink,
              ),
            ),
            const SizedBox(height: 12),
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                _chip('Карточка', false),
                const SizedBox(width: 8),
                _chip('Стикер на своё фото', true),
              ],
            ),
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: const Color(0xFF10141A),
                borderRadius: BorderRadius.circular(16),
              ),
              child: RepaintBoundary(key: _boundaryKey, child: preview),
            ),
            if (_stickerMode) ...[
              SwitchListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                activeTrackColor: _lime.withValues(alpha: .5),
                title: const Text(
                  'Цифры на стикере',
                  style: TextStyle(fontSize: 13.5, color: _ink),
                ),
                value: _showStats,
                onChanged: (v) => setState(() => _showStats = v),
              ),
              const StickerHint(),
              const SizedBox(height: 8),
            ] else
              const SizedBox(height: 10),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: _lime,
                  foregroundColor: const Color(0xFF171C19),
                  minimumSize: const Size(64, 52),
                ),
                onPressed: _busy ? null : () => _send(instagram: true),
                child: const InstagramButtonLabel(),
              ),
            ),
            const SizedBox(height: 8),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                style: OutlinedButton.styleFrom(
                  foregroundColor: _ink,
                  side: BorderSide(color: _ink.withValues(alpha: .3)),
                  minimumSize: const Size(64, 48),
                ),
                onPressed: _busy ? null : _saveToGallery,
                icon: const Icon(Icons.download_rounded, size: 19),
                label: const Text('Сохранить в галерею'),
              ),
            ),
            const SizedBox(height: 8),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton(
                style: OutlinedButton.styleFrom(
                  foregroundColor: _ink,
                  side: BorderSide(color: _ink.withValues(alpha: .3)),
                  minimumSize: const Size(64, 48),
                ),
                onPressed: _busy ? null : () => _send(instagram: false),
                child: const Text('Отправить в другое приложение'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _chip(String label, bool sticker) {
    final selected = _stickerMode == sticker;
    return GestureDetector(
      onTap: () => setState(() => _stickerMode = sticker),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 160),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 7),
        decoration: BoxDecoration(
          color: selected ? _lime.withValues(alpha: .16) : Colors.transparent,
          borderRadius: BorderRadius.circular(999),
          border: Border.all(
            color: selected
                ? _lime.withValues(alpha: .8)
                : _ink.withValues(alpha: .25),
          ),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontSize: 12.5,
            fontWeight: FontWeight.w700,
            color: selected ? _lime : _ink.withValues(alpha: .65),
          ),
        ),
      ),
    );
  }

  Future<File?> _renderToFile() async {
    final boundary = _boundaryKey.currentContext?.findRenderObject()
        as RenderRepaintBoundary?;
    if (boundary == null) return null;
    final image = await boundary.toImage(pixelRatio: 4);
    final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
    if (bytes == null) return null;
    final dir = await getTemporaryDirectory();
    final shareDir = Directory('${dir.path}/insta_share');
    await shareDir.create(recursive: true);
    final file = File(
      '${shareDir.path}/kvartal_run_${DateTime.now().millisecondsSinceEpoch}.png',
    );
    await file.writeAsBytes(bytes.buffer.asUint8List());
    return file;
  }

  Future<void> _saveToGallery() async {
    setState(() => _busy = true);
    try {
      final file = await _renderToFile();
      if (file == null) return;
      final ok = await saveShareImageToGallery(file.path);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(ok
            ? (_stickerMode
                ? 'Росчерк в галерее — клади его на фото и видео в любом редакторе'
                : 'Карточка сохранена в галерею')
            : 'Не получилось сохранить — проверь доступ к памяти'),
      ));
      if (ok) Navigator.of(context).pop();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _send({required bool instagram}) async {
    setState(() => _busy = true);
    try {
      final file = await _renderToFile();
      if (file == null) return;

      if (instagram) {
        var ok = false;
        if (_metaAppId.isNotEmpty && Platform.isAndroid) {
          ok = await _instaChannel.invokeMethod<bool>(
                _stickerMode ? 'shareSticker' : 'shareBackground',
                {'path': file.path, 'appId': _metaAppId},
              ) ??
              false;
        }
        if (ok) {
          if (mounted) Navigator.of(context).pop();
          return;
        }
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('Инстаграм недоступен — отправляю обычным шарингом'),
          ));
        }
      }
      await Share.shareXFiles(
        [XFile(file.path, mimeType: 'image/png')],
        text: 'Моя пробежка в КВАРТАЛЕ',
      );
      if (mounted) Navigator.of(context).pop();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}

/// Сторис-карточка 9:16, эталон v2 «Выше Стравы» (утверждён 06.09.2026):
/// росчерк с градиентом лайм→бирюза, км-точки, старт-кольцо и финиш-флаг на
/// сетке города; при захвате — заголовок-вызов и гекс-контуры кварталов
/// (стилизованные — адрес не выдают); медаль забега — настоящим штампом.
class RunStoryCard extends StatelessWidget {
  final RunShareData data;
  final String runner;
  final String? city;

  /// Медаль, взятая в этом забеге (окно Паспорта), и сколько ещё сверх неё.
  final MedalFull? medal;
  final int extraAwards;

  /// Баллы за пробежку — если известны (последний синк).
  final int? points;

  const RunStoryCard({
    super.key,
    required this.data,
    required this.runner,
    this.city,
    this.medal,
    this.extraAwards = 0,
    this.points,
  });

  @override
  Widget build(BuildContext context) {
    final d = data;
    final captured = d.capturedZones > 0;
    final date =
        '${d.finishedAt.day.toString().padLeft(2, '0')}.${d.finishedAt.month.toString().padLeft(2, '0')}.${d.finishedAt.year}';
    final time =
        '${d.finishedAt.hour.toString().padLeft(2, '0')}:${d.finishedAt.minute.toString().padLeft(2, '0')}';
    final pace = d.distanceKm < .01 || d.elapsed.inSeconds == 0
        ? '--:--'
        : _fmtPace((d.elapsed.inSeconds / d.distanceKm).round());
    final t = d.temperatureC;

    return Container(
      width: 270,
      height: 480,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(14),
        gradient: const RadialGradient(
          center: Alignment(0, -.8),
          radius: 1.5,
          colors: [Color(0xFF222A33), _bg, Color(0xFF090C10)],
          stops: [0, .55, 1],
        ),
      ),
      child: Stack(
        children: [
          // Сетка города — глубина фона, растворяется к подвалу.
          Positioned.fill(child: CustomPaint(painter: _CityGridPainter())),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: d.route.length >= 2
                    ? Padding(
                        padding: const EdgeInsets.fromLTRB(10, 8, 10, 0),
                        child: CustomPaint(
                          painter: _CardTrackPainter(
                            d.route,
                            hexes: captured ? d.capturedZones : 0,
                          ),
                          child: const SizedBox.expand(),
                        ),
                      )
                    : Center(
                        child: Icon(
                          Icons.route,
                          size: 64,
                          color: _lime.withValues(alpha: .4),
                        ),
                      ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (medal != null) ...[
                      _RunMedalPlaque(medal: medal!, extra: extraAwards),
                      const SizedBox(height: 9),
                    ],
                    // Микspace-строка: дата · время · [погода] · город · бегун.
                    // FittedBox, а не многоточие: имя бегуна дорезать нельзя —
                    // длинная строка чуть ужимает кегль и влезает целиком.
                    FittedBox(
                      fit: BoxFit.scaleDown,
                      alignment: Alignment.centerLeft,
                      child: Text.rich(
                        TextSpan(
                          children: [
                            TextSpan(text: '$date · $time'),
                            if (t != null)
                              TextSpan(
                                text: ' · ${t > 0 ? '+' : ''}$t°C',
                                style: const TextStyle(color: _cyan),
                              ),
                            TextSpan(
                              text:
                                  '${city == null ? '' : ' · ${city!.toUpperCase()}'} · ${runner.toUpperCase()}',
                            ),
                          ],
                        ),
                        maxLines: 1,
                        style: const TextStyle(
                          fontSize: 7.5,
                          letterSpacing: .8,
                          fontWeight: FontWeight.w700,
                          color: _muted,
                        ),
                      ),
                    ),
                    const SizedBox(height: 7),
                    if (captured) ...[
                      Text(
                        'Забрал ${d.capturedZones} ${_qWord(d.capturedZones)}',
                        style: const TextStyle(
                          fontFamily: AppTheme.fontDisplay,
                          fontSize: 21,
                          fontWeight: FontWeight.w900,
                          height: 1.1,
                          color: _ink,
                        ),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        '${d.distanceKm.toStringAsFixed(2)} км · вернуть можно только бегом',
                        style: const TextStyle(fontSize: 11, color: _muted),
                      ),
                    ] else
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.baseline,
                        textBaseline: TextBaseline.alphabetic,
                        children: [
                          Text(
                            d.distanceKm.toStringAsFixed(2),
                            style: const TextStyle(
                              fontFamily: AppTheme.fontDisplay,
                              fontSize: 40,
                              fontWeight: FontWeight.w900,
                              letterSpacing: -1.5,
                              height: 1,
                              color: _ink,
                            ),
                          ),
                          const SizedBox(width: 5),
                          const Text(
                            'КМ',
                            style: TextStyle(
                              fontFamily: AppTheme.fontDisplay,
                              fontSize: 15,
                              fontWeight: FontWeight.w800,
                              color: _lime,
                            ),
                          ),
                        ],
                      ),
                    const SizedBox(height: 9),
                    _statLine(
                      elapsed: _fmtElapsed(d.elapsed),
                      pace: pace,
                      captured: captured,
                      zones: d.capturedZones,
                    ),
                    const SizedBox(height: 12),
                    const BrandMark(),
                  ],
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  /// Статы строкой с тонкими разделителями — вместо коробок-чипов (v2).
  Widget _statLine({
    required String elapsed,
    required String pace,
    required bool captured,
    required int zones,
  }) {
    final items = <(String, String, bool)>[
      (elapsed, 'ВРЕМЯ', false),
      (pace, 'ТЕМП /КМ', false),
      if (captured)
        ('+$zones', 'КВАРТАЛА', true)
      else if (points != null)
        ('+$points', 'БАЛЛОВ', false),
    ];
    return Container(
      padding: const EdgeInsets.only(top: 8),
      decoration: BoxDecoration(
        border: Border(
          top: BorderSide(color: _muted.withValues(alpha: .22)),
        ),
      ),
      child: Row(
        children: [
          for (var i = 0; i < items.length; i++) ...[
            if (i > 0)
              Container(
                width: 1,
                height: 24,
                margin: const EdgeInsets.symmetric(horizontal: 10),
                color: _muted.withValues(alpha: .22),
              ),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    items[i].$1,
                    style: TextStyle(
                      fontFamily: AppTheme.fontDisplay,
                      fontSize: 14,
                      fontWeight: FontWeight.w800,
                      letterSpacing: -.3,
                      color: items[i].$3 ? _lime : _ink,
                    ),
                  ),
                  const SizedBox(height: 1),
                  Text(
                    items[i].$2,
                    style: const TextStyle(
                      fontSize: 7,
                      letterSpacing: 1.2,
                      fontWeight: FontWeight.w700,
                      color: _muted,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// Плашка медали, взятой в этом забеге, — настоящий штамп (ход Стравы
/// апреля-2025 «награды на маршруте», но у нас металл, а не бейдж).
class _RunMedalPlaque extends StatelessWidget {
  final MedalFull medal;
  final int extra;
  const _RunMedalPlaque({required this.medal, required this.extra});

  @override
  Widget build(BuildContext context) {
    final e = medal.state.engraving;
    final sub = [
      medal.def.tier.title.toLowerCase(),
      medal.def.cat.title.toLowerCase(),
      if (e != null && e.v.isNotEmpty) '${e.u.toLowerCase()} ${e.v}',
    ].join(' · ');
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
      decoration: BoxDecoration(
        color: _panel.withValues(alpha: .72),
        borderRadius: BorderRadius.circular(11),
        border: Border.all(color: _lime.withValues(alpha: .35)),
      ),
      child: Row(
        children: [
          Image.asset(medal.def.asset, width: 30, height: 30),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                FittedBox(
                  fit: BoxFit.scaleDown,
                  alignment: Alignment.centerLeft,
                  child: Text(
                    'МЕДАЛЬ «${medal.def.name.toUpperCase()}» — ВЗЯТА В ЭТОМ ЗАБЕГЕ${extra > 0 ? ' +$extra' : ''}',
                    maxLines: 1,
                    style: const TextStyle(
                      fontSize: 10,
                      fontWeight: FontWeight.w800,
                      letterSpacing: .4,
                      color: _ink,
                    ),
                  ),
                ),
                const SizedBox(height: 1),
                FittedBox(
                  fit: BoxFit.scaleDown,
                  alignment: Alignment.centerLeft,
                  child: Text(
                    sub,
                    maxLines: 1,
                    style: const TextStyle(fontSize: 8, color: _muted),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// Тонкая сетка города поверх радиального фона; растворяется к подвалу,
/// чтобы не спорить с данными.
class _CityGridPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    const step = 44.0;
    final paint = Paint()
      ..strokeWidth = 1
      ..shader = ui.Gradient.linear(
        Offset.zero,
        Offset(0, size.height),
        [
          _muted.withValues(alpha: .06),
          _muted.withValues(alpha: .06),
          _muted.withValues(alpha: 0),
        ],
        [0, .62, .88],
      );
    for (var x = step; x < size.width; x += step) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), paint);
    }
    for (var y = step; y < size.height; y += step) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), paint);
    }
  }

  @override
  bool shouldRepaint(covariant _CityGridPainter old) => false;
}

/// Росчерк карточки v2: градиент лайм→бирюза вдоль пути, свечение, км-точки,
/// старт-кольцо, финиш-флаг; при захвате — стилизованный кластер гексов
/// (форма не географическая — адрес не выдаёт).
class _CardTrackPainter extends CustomPainter {
  final List<LatLng> route;
  final int hexes;
  _CardTrackPainter(this.route, {this.hexes = 0});

  @override
  void paint(Canvas canvas, Size size) {
    if (route.length < 2) return;
    var minLat = route.first.latitude, maxLat = minLat;
    var minLng = route.first.longitude, maxLng = minLng;
    for (final p in route) {
      minLat = p.latitude < minLat ? p.latitude : minLat;
      maxLat = p.latitude > maxLat ? p.latitude : maxLat;
      minLng = p.longitude < minLng ? p.longitude : minLng;
      maxLng = p.longitude > maxLng ? p.longitude : maxLng;
    }
    final latSpan = (maxLat - minLat).abs().clamp(1e-6, double.infinity);
    final lngSpan = (maxLng - minLng).abs().clamp(1e-6, double.infinity);
    const pad = 22.0;
    final scale = ((size.width - pad * 2) / lngSpan)
        .clamp(0, (size.height - pad * 2) / latSpan)
        .toDouble();
    final w = lngSpan * scale, h = latSpan * scale;
    final ox = (size.width - w) / 2, oy = (size.height - h) / 2;
    Offset pt(LatLng p) => Offset(
          ox + (p.longitude - minLng) * scale,
          oy + (maxLat - p.latitude) * scale,
        );

    // Гексы захвата — под треком, кластером у верхней трети росчерка.
    if (hexes > 0) {
      final r = size.shortestSide * .13;
      final c = Offset(ox + w / 2, oy + h * .3);
      final offsets = [
        Offset(-r, -r * .6),
        Offset(r, -r * .6),
        Offset(0, r * 1.1),
      ];
      for (var i = 0; i < math.min(hexes, 3); i++) {
        final hc = c + offsets[i];
        final hex = Path();
        for (var k = 0; k < 6; k++) {
          final a = math.pi / 180 * (60 * k - 90);
          final p = hc + Offset(math.cos(a), math.sin(a)) * r;
          k == 0 ? hex.moveTo(p.dx, p.dy) : hex.lineTo(p.dx, p.dy);
        }
        hex.close();
        canvas.drawPath(
          hex,
          Paint()..color = _lime.withValues(alpha: .085 - i * .012),
        );
        canvas.drawPath(
          hex,
          Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = 1.4
            ..color = _lime.withValues(alpha: .5 - i * .06),
        );
      }
    }

    final path = Path()..moveTo(pt(route.first).dx, pt(route.first).dy);
    for (final p in route.skip(1)) {
      path.lineTo(pt(p).dx, pt(p).dy);
    }

    // Градиент вдоль диагонали рамки трека: старт-лайм → финиш-бирюза.
    final shader = ui.Gradient.linear(
      Offset(ox, oy + h),
      Offset(ox + w, oy),
      const [_lime, _cyan],
    );
    canvas.drawPath(
      path,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 9
        ..strokeJoin = StrokeJoin.round
        ..strokeCap = StrokeCap.round
        ..shader = shader
        ..color = Colors.white.withValues(alpha: .55)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 7),
    );
    canvas.drawPath(
      path,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 4.5
        ..strokeJoin = StrokeJoin.round
        ..strokeCap = StrokeCap.round
        ..shader = shader,
    );

    // Км-точки: честные отметки каждого целого километра вдоль пути.
    const dist = Distance();
    var total = 0.0;
    for (var i = 1; i < route.length; i++) {
      total += dist(route[i - 1], route[i]);
    }
    if (total >= 1000) {
      var cum = 0.0;
      var nextKm = 1;
      for (var i = 1; i < route.length && nextKm <= 30; i++) {
        final seg = dist(route[i - 1], route[i]);
        while (cum + seg >= nextKm * 1000 && nextKm <= 30) {
          // Последний км сливается с финиш-флагом — не рисуем.
          if (nextKm * 1000 > total - 120) break;
          final f = seg == 0 ? 0.0 : (nextKm * 1000 - cum) / seg;
          final a = pt(route[i - 1]), b = pt(route[i]);
          final p = Offset.lerp(a, b, f)!;
          final col = Color.lerp(_lime, _cyan, nextKm * 1000 / total)!;
          canvas.drawCircle(p, 2.6, Paint()..color = const Color(0xFF0E1116));
          canvas.drawCircle(
            p,
            2.6,
            Paint()
              ..style = PaintingStyle.stroke
              ..strokeWidth = 1.6
              ..color = col,
          );
          nextKm++;
        }
        cum += seg;
      }
    }

    // Старт-кольцо.
    final start = pt(route.first);
    canvas.drawCircle(start, 6, Paint()..color = const Color(0xFF171C19));
    canvas.drawCircle(
      start,
      6,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3
        ..color = _lime,
    );
    // Финиш-флаг (бирюза — конец градиента).
    final fin = pt(route.last);
    canvas.drawLine(
      fin,
      fin - const Offset(0, 20),
      Paint()
        ..color = Colors.white
        ..strokeWidth = 2.6
        ..strokeCap = StrokeCap.round,
    );
    final flag = Path()
      ..moveTo(fin.dx, fin.dy - 20)
      ..lineTo(fin.dx + 15, fin.dy - 15.5)
      ..lineTo(fin.dx, fin.dy - 11)
      ..close();
    canvas.drawPath(flag, Paint()..color = _cyan);
  }

  @override
  bool shouldRepaint(covariant _CardTrackPainter old) =>
      old.route != route || old.hexes != hexes;
}

/// Прозрачный стикер: росчерк + (опционально) цифры с тенями. Ноль подложки.
class RunSticker extends StatelessWidget {
  final RunShareData data;
  final bool showStats;

  const RunSticker({super.key, required this.data, required this.showStats});

  @override
  Widget build(BuildContext context) {
    final d = data;
    final pace = d.distanceKm < .01 || d.elapsed.inSeconds == 0
        ? '--:--'
        : _fmtPace((d.elapsed.inSeconds / d.distanceKm).round());
    return SizedBox(
      width: 230,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 230,
            height: 190,
            child: d.route.length >= 2
                ? CustomPaint(painter: _StickerTrackPainter(d.route))
                : const SizedBox.shrink(),
          ),
          if (showStats) ...[
            const SizedBox(height: 8),
            Text(
              '${d.distanceKm.toStringAsFixed(2)} КМ',
              style: TextStyle(
                fontFamily: AppTheme.fontDisplay,
                fontSize: 30,
                fontWeight: FontWeight.w900,
                letterSpacing: -1,
                height: 1,
                color: Colors.white,
                shadows: [
                  Shadow(
                    blurRadius: 14,
                    color: Colors.black.withValues(alpha: .6),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 5),
            Text(
              '${_fmtElapsed(d.elapsed)} · $pace /км',
              style: TextStyle(
                fontSize: 12.5,
                fontWeight: FontWeight.w800,
                color: Colors.white,
                shadows: [
                  Shadow(
                    blurRadius: 10,
                    color: Colors.black.withValues(alpha: .65),
                  ),
                ],
              ),
            ),
          ],
          const SizedBox(height: 9),
          // Вариант А и на стикере: без капсулы, тень держит читаемость.
          const BrandMark(shadow: true),
        ],
      ),
    );
  }
}

/// Трек стикера: неоновый росчерк со свечением, старт-точка и финиш-флаг.
/// Без сетки и подложки — прозрачность священна.
class _StickerTrackPainter extends CustomPainter {
  final List<LatLng> route;
  _StickerTrackPainter(this.route);

  @override
  void paint(Canvas canvas, Size size) {
    if (route.length < 2) return;
    var minLat = route.first.latitude, maxLat = minLat;
    var minLng = route.first.longitude, maxLng = minLng;
    for (final p in route) {
      minLat = p.latitude < minLat ? p.latitude : minLat;
      maxLat = p.latitude > maxLat ? p.latitude : maxLat;
      minLng = p.longitude < minLng ? p.longitude : minLng;
      maxLng = p.longitude > maxLng ? p.longitude : maxLng;
    }
    final latSpan = (maxLat - minLat).abs().clamp(1e-6, double.infinity);
    final lngSpan = (maxLng - minLng).abs().clamp(1e-6, double.infinity);
    const pad = 18.0;
    final scale = ((size.width - pad * 2) / lngSpan)
        .clamp(0, (size.height - pad * 2) / latSpan)
        .toDouble();
    final w = lngSpan * scale, h = latSpan * scale;
    final ox = (size.width - w) / 2, oy = (size.height - h) / 2;
    Offset pt(LatLng p) => Offset(
          ox + (p.longitude - minLng) * scale,
          oy + (maxLat - p.latitude) * scale,
        );

    final path = Path()..moveTo(pt(route.first).dx, pt(route.first).dy);
    for (final p in route.skip(1)) {
      path.lineTo(pt(p).dx, pt(p).dy);
    }

    final glow = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 9
      ..strokeJoin = StrokeJoin.round
      ..strokeCap = StrokeCap.round
      ..color = _lime.withValues(alpha: .55)
      ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 7);
    final line = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 4.5
      ..strokeJoin = StrokeJoin.round
      ..strokeCap = StrokeCap.round
      ..color = _lime;
    canvas.drawPath(path, glow);
    canvas.drawPath(path, line);

    // Старт-точка.
    final start = pt(route.first);
    canvas.drawCircle(
      start,
      6,
      Paint()..color = const Color(0xFF171C19),
    );
    canvas.drawCircle(
      start,
      6,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3
        ..color = _lime,
    );
    // Финиш-флаг.
    final fin = pt(route.last);
    final pole = Paint()
      ..color = Colors.white
      ..strokeWidth = 2.6
      ..strokeCap = StrokeCap.round;
    canvas.drawLine(fin, fin - const Offset(0, 20), pole);
    final flag = Path()
      ..moveTo(fin.dx, fin.dy - 20)
      ..lineTo(fin.dx + 15, fin.dy - 15.5)
      ..lineTo(fin.dx, fin.dy - 11)
      ..close();
    canvas.drawPath(flag, Paint()..color = _lime);
  }

  @override
  bool shouldRepaint(covariant _StickerTrackPainter old) =>
      old.route != route;
}

String _fmtElapsed(Duration e) {
  final h = e.inHours;
  final m = e.inMinutes % 60;
  final s = e.inSeconds % 60;
  if (h > 0) {
    return '${h.toString().padLeft(2, '0')}:${m.toString().padLeft(2, '0')}:${s.toString().padLeft(2, '0')}';
  }
  return '${m.toString().padLeft(2, '0')}:${s.toString().padLeft(2, '0')}';
}

String _fmtPace(int sec) =>
    '${(sec ~/ 60).toString().padLeft(2, '0')}:${(sec % 60).toString().padLeft(2, '0')}';

String _qWord(int n) {
  final mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 14) return 'кварталов';
  return switch (n % 10) {
    1 => 'квартал',
    2 || 3 || 4 => 'квартала',
    _ => 'кварталов',
  };
}
