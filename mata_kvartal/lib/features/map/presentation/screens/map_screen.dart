import '../../../../shared/widgets/tab_visibility.dart';
import 'dart:async' show Timer;
import 'dart:math' show max;
import 'dart:ui' show ImageFilter;
import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../../core/theme/app_colors.dart';
import '../../data/location_provider.dart';
import '../../data/zone_provider.dart';
import '../../../../core/theme/app_theme.dart';
import '../../../league/data/division_provider.dart';
import '../../../league/data/league_provider.dart';
import '../../../weather/domain/run_window.dart';
import '../../../run/data/run_provider.dart';
import '../../../territory/data/territory_provider.dart';
import '../../../weather/data/weather_provider.dart';
import '../../../weather/presentation/weather_background.dart';
import '../../../weather/presentation/weather_view.dart';
import '../../../../shared/widgets/kvartal_logo.dart';

class MapScreen extends ConsumerStatefulWidget {
  const MapScreen({super.key});

  @override
  ConsumerState<MapScreen> createState() => _MapScreenState();
}

class _MapScreenState extends ConsumerState<MapScreen> with TabVisibility {
  final _mapController = MapController();
  final _flashing = <String>{};

  // Ключ CARTO приходит из сборки (--dart-define=CARTO_API_KEY, секрет — не в репо).
  // Есть ключ → чистые тайлы CARTO Voyager; нет ключа (локальная сборка без секрета)
  // → OpenStreetMap, чтобы карта всё равно работала.
  static const _cartoKey = String.fromEnvironment('CARTO_API_KEY');
  bool get _hasCarto => _cartoKey.isNotEmpty;

  bool _followUser = true;

  // Легенда карты: свёрнута по умолчанию, не закрывает карту.

  bool _legendOpen = false;
  bool _baseMapFailed = false;
  int _tileErrorCount = 0;
  int _tileLayerReloadId = 0;
  Timer? _territoryDebounce;

  /// Уровень 1 «живой карты» (D-09): пока экран открыт — периодически
  /// перетягиваем видимую область, чтобы видеть чужие захваты своей территории.
  /// Свой захват применяется мгновенно (territoryProvider.capture). При росте —
  /// перейти на дельты/WebSocket (Уровень 2/3).
  Timer? _territoryRefreshTimer;
  static const _territoryRefreshInterval = Duration(seconds: 12);

  /// Подгрузить реальные территории (PostGIS) для видимой области карты.
  void _scheduleTerritoryLoad() {
    _territoryDebounce?.cancel();
    _territoryDebounce = Timer(
      const Duration(milliseconds: 600),
      _loadTerritories,
    );
  }

  /// Нотифаер территорий, снятый один раз при инициализации: таймер и колбэки
  /// камеры срабатывают и после ухода с вкладки, а искать провайдер через
  /// деактивированный элемент нельзя.
  late final TerritoryNotifier _territories;

  void _loadTerritories() {
    if (!mounted) return;
    final LatLngBounds bounds;
    try {
      bounds = _mapController.camera.visibleBounds;
    } catch (_) {
      return; // камера ещё не готова
    }
    _territories.loadBbox(
          minLng: bounds.west,
          minLat: bounds.south,
          maxLng: bounds.east,
          maxLat: bounds.north,
        );
  }

  void _handleTileError() {
    _tileErrorCount++;
    if (_tileErrorCount < 4 || _baseMapFailed) return;

    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || _baseMapFailed) return;
      setState(() => _baseMapFailed = true);
    });
  }

  void _retryBaseMap() {
    setState(() {
      _baseMapFailed = false;
      _tileErrorCount = 0;
      _tileLayerReloadId++;
    });
  }

  @override
  void initState() {
    super.initState();
    _territories = ref.read(territoryProvider.notifier);
    _territoryRefreshTimer = Timer.periodic(_territoryRefreshInterval, (_) {
      // Карта живёт между переключениями вкладок (см. app_router), поэтому на
      // скрытой вкладке сеть не дёргаем — иначе опрос шёл бы фоном всегда.
      if (!isTabVisible) return;
      _loadTerritories();
      // Досылаем отложенные офлайн-захваты, когда вернулась связь (S-07).
      _territories.flushQueue();
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _centerOnCurrentLocation();
      _scheduleTerritoryLoad();
    });
  }

  @override
  void onTabShown() {
    // Вернулись на карту — сразу подтягиваем захваты за время отсутствия.
    _scheduleTerritoryLoad();
    _territories.flushQueue();
  }

  @override
  void dispose() {
    _territoryDebounce?.cancel();
    _territoryRefreshTimer?.cancel();
    _mapController.dispose();
    super.dispose();
  }

  Future<void> _centerOnCurrentLocation() async {
    final pos = await ref.read(currentPositionProvider.future);
    if (!mounted || pos == null) return;
    _mapController.move(pos.toLatLng, max(_mapController.camera.zoom, 15));
    _scheduleTerritoryLoad();
  }

  @override
  Widget build(BuildContext context) {
    final zonesAsync = ref.watch(zoneProvider);
    final zones = zonesAsync.valueOrNull ?? const <BlockZone>[];
    final territories = ref.watch(territoryProvider).territories;
    final posAsync = ref.watch(positionStreamProvider);
    final runState = ref.watch(runProvider);
    final closureStatus = ref
        .read(zoneProvider.notifier)
        .inspectLoopClosure(runState.route);
    ref.listen(positionStreamProvider, (_, next) {
      final pos = next.valueOrNull;
      if (!_followUser || pos == null) return;
      // Статус берём из значения, снятого в build: ref.read в отложенном
      // колбэке падает, если экран уже ушёл с вкладки.
      if (runState.status != RunStatus.idle) return;
      _mapController.move(pos.toLatLng, _mapController.camera.zoom);
    });
    ref.listen(runProvider, (previous, next) {
      if (!context.mounted) return;
      if (!_followUser || next.status == RunStatus.idle || next.route.isEmpty) {
        return;
      }
      final point = next.route.last;
      final previousPoint = previous?.route.isNotEmpty == true
          ? previous!.route.last
          : null;
      if (previousPoint == point) return;
      _mapController.move(point, _mapController.camera.zoom);
    });
    return Scaffold(
      backgroundColor: AppColors.bgDark,
      body: Stack(
        children: [
          // ── Map ──────────────────────────────────────────────────────────
          FlutterMap(
            mapController: _mapController,
            options: MapOptions(
              initialCenter: yakutskCenter,
              initialZoom: 16,
              minZoom: 5,
              maxZoom: 20,
              onTap: (_, latLng) => _onMapTap(latLng),
              onMapEvent: (e) {
                if (e is MapEventMove && e.source == MapEventSource.onDrag) {
                  if (_followUser) setState(() => _followUser = false);
                  if (_legendOpen) setState(() => _legendOpen = false);
                }
                // Перезагружаем территории только на РУЧНЫЕ жесты (пан/зум),
                // но не на программное авто-слежение во время бега — иначе
                // дёргали бы бэк каждую секунду забега (на улице связи нет).
                if ((e is MapEventMoveEnd ||
                        e is MapEventFlingAnimationEnd ||
                        e is MapEventDoubleTapZoomEnd ||
                        e is MapEventScrollWheelZoom) &&
                    e.source != MapEventSource.mapController) {
                  _scheduleTerritoryLoad();
                }
              },
            ),
            children: [
              // Подложка: CARTO Voyager (растровые тайлы) с ключом из сборки. Без
              // ключа — OpenStreetMap (локальная сборка работает). Векторный
              // OpenFreeMap убран ранее — отрисовывался серым (D-26). CARTO сворачивает
              // растр → на запуске апгрейд на вектор (MapLibre).
              TileLayer(
                key: ValueKey(_tileLayerReloadId),
                urlTemplate: _hasCarto
                    ? 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png?key=$_cartoKey'
                    : 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                subdomains: _hasCarto ? const ['a', 'b', 'c', 'd'] : const [],
                userAgentPackageName: 'ru.mata.kvartal',
                maxNativeZoom: 19,
                errorTileCallback: (_, __, ___) => _handleTileError(),
              ),

              // Атрибуция обязательна (условие бесплатного тарифа CARTO): CARTO + OSM.
              RichAttributionWidget(
                alignment: AttributionAlignment.bottomLeft,
                attributions: [
                  if (_hasCarto) const TextSourceAttribution('CARTO'),
                  const TextSourceAttribution('© OpenStreetMap'),
                ],
              ),
              // Локальный слой «захваченных областей» убран («Идеальный
              // маршрут», 03.09): он рисовал СЫРОЙ клиентский полигон поверх
              // серверного и давал двойной контур. Источник правды один —
              // серверные territories ниже.

              // City block territory polygons
              PolygonLayer(
                polygons: zones.map((z) {
                  final flash = _flashing.contains(z.id);
                  return Polygon(
                    points: z.vertices,
                    color: _fill(z.owner, flash: flash),
                    borderColor: _border(z.owner, flash: flash),
                    borderStrokeWidth: flash ? 3.5 : 1.5,
                  );
                }).toList(),
              ),

              // Реальные территории с сервера (PostGIS, D-09): мои/клуб/чужие.
              if (territories.isNotEmpty)
                PolygonLayer(
                  polygons: [
                    for (final t in territories)
                      for (final ring in t.rings)
                        Polygon(
                          points: ring,
                          // Видимый decay (Ф2): чем ближе конец удержания,
                          // тем бледнее квартал — землю пора обновлять бегом.
                          color: _territoryFill(
                            t.rel,
                            freshness: _freshness(t.holdHoursLeft),
                          ),
                          borderColor: _territoryBorder(
                            t.rel,
                            freshness: _freshness(t.holdHoursLeft),
                          ),
                          borderStrokeWidth: 1.6,
                        ),
                  ],
                ),

              // Run route line
              if (runState.status != RunStatus.idle &&
                  runState.route.length > 1)
                PolylineLayer(
                  polylines: [
                    Polyline(
                      points: runState.route,
                      color: AppColors.electricBlue,
                      strokeWidth: 2.4,
                      borderColor: AppColors.electricBlue.withValues(alpha: 0),
                      borderStrokeWidth: 0,
                    ),
                  ],
                ),
              if (runState.status != RunStatus.idle &&
                  runState.route.isNotEmpty)
                MarkerLayer(
                  markers: [
                    Marker(
                      point: runState.route.first,
                      width: 30,
                      height: 34,
                      child: _RoutePointMarker(
                        label: 'Старт',
                        color: AppColors.success,
                        icon: CupertinoIcons.play_fill,
                      ),
                    ),
                  ],
                ),

              // Маркер пользователя. Во время бега берём ПОСЛЕДНЮЮ точку
              // сглаженного (Калман) трека — метка и линия совпадают. Метка
              // плавно «скользит» между фиксами (анимация), а не прыгает.
              // Вне бега — текущая позиция из потока.
              _AnimatedUserMarker(
                target:
                    runState.status != RunStatus.idle &&
                        runState.route.isNotEmpty
                    ? runState.route.last
                    : posAsync.valueOrNull?.toLatLng,
                isRunning: runState.status == RunStatus.active,
              ),
            ],
          ),

          // ── Top bar + legend ─────────────────────────────────────────────
          Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: SafeArea(
              bottom: false,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Padding(
                    // Чуть опускаем верхние чипы от статус-бара — как на других экранах.
                    padding: const EdgeInsets.fromLTRB(14, 12, 14, 6),
                    child: Row(
                      children: [
                        const _KvartalTopLogo(),
                        const Spacer(),
                        _WeatherChip(),
                      ],
                    ),
                  ),
                  // Блок «Сегодня» (Ф2): окно бега · дивизион · неделя —
                  // сразу под шапкой (раскладка владельца, 01.09).
                  // Во время бега прячется — не мешать.
                  if (runState.status == RunStatus.idle) const _TodayRow(),
                  Padding(
                    padding: const EdgeInsets.only(left: 14, top: 2, bottom: 4),
                    // Легенда сворачиваемая: тап — развернуть, тап по карте
                    // или пан — свернётся сама. Свёрнутая не закрывает карту.
                    child: _CollapsibleLegend(
                      open: _legendOpen,
                      onToggle: () =>
                          setState(() => _legendOpen = !_legendOpen),
                    ),
                  ),
                ],
              ),
            ),
          ),

          // ── Loading indicator ────────────────────────────────────────────
          if (zonesAsync is AsyncLoading)
            Center(
              child: _Glass(
                padding: EdgeInsets.symmetric(horizontal: 20, vertical: 14),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: AppColors.electricBlue,
                      ),
                    ),
                    SizedBox(width: 12),
                    Text(
                      'Загружаем кварталы улиц Якутска...',
                      style: TextStyle(color: AppColors.ink, fontSize: 13),
                    ),
                  ],
                ),
              ),
            ),

          // ── Error banner (центр экрана) ──────────────────────────────────
          if (zonesAsync is AsyncError)
            Center(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 40),
                child: _Glass(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 24,
                    vertical: 20,
                  ),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        CupertinoIcons.wifi_slash,
                        color: AppColors.error,
                        size: 24,
                      ),
                      const SizedBox(height: 8),
                      Text(
                        'Зоны не загружены',
                        style: TextStyle(
                          color: AppColors.ink,
                          fontSize: 13,
                          fontWeight: FontWeight.w700,
                        ),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 4),
                      Text(
                        'GPS работает.\nЗапусти бэкенд и нажми «Повторить».',
                        style: TextStyle(color: AppColors.muted, fontSize: 11),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 12),
                      GestureDetector(
                        onTap: () => ref.read(zoneProvider.notifier).retry(),
                        child: Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 16,
                            vertical: 8,
                          ),
                          decoration: BoxDecoration(
                            color: AppColors.graphite,
                            borderRadius: BorderRadius.circular(10),
                          ),
                          child: const Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(
                                CupertinoIcons.arrow_clockwise,
                                color: Colors.white,
                                size: 12,
                              ),
                              SizedBox(width: 5),
                              Text(
                                'Повторить',
                                style: TextStyle(
                                  color: Colors.white,
                                  fontWeight: FontWeight.w700,
                                  fontSize: 13,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),

          // ── Bottom area: buttons + stats ─────────────────────────────────
          if (_baseMapFailed)
            Center(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 28),
                child: _MapErrorNotice(onRetry: _retryBaseMap),
              ),
            ),
          Positioned(
            bottom: 0,
            left: 0,
            right: 0,
            child: SafeArea(
              top: false,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (!_followUser)
                    Padding(
                      padding: const EdgeInsets.only(right: 16, bottom: 10),
                      child: _IconBtn(
                        icon: CupertinoIcons.location_fill,
                        color: AppColors.electricBlue,
                        onTap: () {
                          setState(() => _followUser = true);
                          final point =
                              runState.status != RunStatus.idle &&
                                  runState.route.isNotEmpty
                              ? runState.route.last
                              : posAsync.valueOrNull?.toLatLng;
                          if (point == null) return;
                          _mapController.move(
                            point,
                            _mapController.camera.zoom,
                          );
                        },
                      ),
                    ),
                  Padding(
                    // Плита «Бег» приподнята над баром — панели нужен воздух.
                    padding: const EdgeInsets.only(bottom: 16),
                    child: _BottomPanel(
                      runState: runState,
                      territories: territories,
                      closureStatus: closureStatus,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// Тап по карте — паспорт квартала (Ф2): чей, защита, как забрать.
  void _onMapTap(LatLng point) {
    // Тап по карте сворачивает развёрнутую легенду (следующий тап — паспорт).
    if (_legendOpen) {
      setState(() => _legendOpen = false);
      return;
    }
    final territories = ref.read(territoryProvider).territories;
    for (final t in territories) {
      for (final ring in t.rings) {
        if (_pointInPolygon(point, ring)) {
          _showQuarterPassport(
            rel: t.rel,
            holdHoursLeft: t.holdHoursLeft,
            ownerName: t.ownerName,
            capturedAtMs: t.capturedAtMs,
          );
          return;
        }
      }
    }
    final zones = ref.read(zoneProvider).valueOrNull ?? const <BlockZone>[];
    for (final z in zones) {
      if (_pointInPolygon(point, z.vertices)) {
        _showQuarterPassport(
          rel: switch (z.owner) {
            ZoneOwner.mine => TerritoryRel.mine,
            ZoneOwner.club => TerritoryRel.club,
            ZoneOwner.enemy => TerritoryRel.enemy,
            ZoneOwner.free => null,
          },
          holdHoursLeft: null,
        );
        return;
      }
    }
  }

  static String _heldLabel(int capturedAtMs) {
    final captured =
        DateTime.fromMillisecondsSinceEpoch(capturedAtMs);
    final days = DateTime.now().difference(captured).inDays;
    if (days <= 0) return 'Захвачен сегодня';
    if (days == 1) return 'Держит 1 день';
    final tail = days % 10;
    final word = (days % 100 >= 11 && days % 100 <= 14)
        ? 'дней'
        : tail == 1
            ? 'день'
            : (tail >= 2 && tail <= 4)
                ? 'дня'
                : 'дней';
    return 'Держит $days $word';
  }

  static bool _pointInPolygon(LatLng p, List<LatLng> poly) {
    var inside = false;
    for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      final a = poly[i];
      final b = poly[j];
      if ((a.latitude > p.latitude) != (b.latitude > p.latitude) &&
          p.longitude <
              (b.longitude - a.longitude) *
                      (p.latitude - a.latitude) /
                      (b.latitude - a.latitude) +
                  a.longitude) {
        inside = !inside;
      }
    }
    return inside;
  }

  void _showQuarterPassport({
    TerritoryRel? rel,
    double? holdHoursLeft,
    String? ownerName,
    int capturedAtMs = 0,
  }) {
    final (title, color, note) = switch (rel) {
      TerritoryRel.mine => (
        'Мой квартал',
        AppColors.lime,
        'Это твоя земля. Бегай рядом, чтобы её удерживать.',
      ),
      TerritoryRel.club => (
        'Квартал клуба',
        AppColors.teal,
        'Держит твой клуб. Общая оборона — общая заслуга.',
      ),
      TerritoryRel.enemy => (
        ownerName != null && ownerName.isNotEmpty
            ? 'Квартал: $ownerName'
            : 'Чужой квартал',
        AppColors.warm,
        'Замкни маршрут вокруг него — и он твой.',
      ),
      null => (
        'Ничей квартал',
        AppColors.zoneNeutral,
        'Свободная земля. Замкни маршрут вокруг — и он твой.',
      ),
    };
    final protected = holdHoursLeft != null && holdHoursLeft > 0;
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: AppColors.paper,
      builder: (sheetContext) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 18, 20, 18),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    width: 34,
                    height: 34,
                    decoration: BoxDecoration(
                      color: color,
                      borderRadius: BorderRadius.circular(11),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      title,
                      style: TextStyle(
                        fontFamily: AppTheme.fontDisplay,
                        fontSize: 18,
                        fontWeight: FontWeight.w800,
                        color: AppColors.ink,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              if (capturedAtMs > 0) ...[
                Text(
                  _heldLabel(capturedAtMs),
                  style: TextStyle(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w600,
                    color: AppColors.muted,
                  ),
                ),
                const SizedBox(height: 6),
              ],
              if (holdHoursLeft != null) ...[
                // Прочность квартала: сколько удержания осталось (Ф2, decay).
                ClipRRect(
                  borderRadius: BorderRadius.circular(3),
                  child: LinearProgressIndicator(
                    value: (holdHoursLeft / 168).clamp(0.0, 1.0),
                    minHeight: 5,
                    backgroundColor: AppColors.soft,
                    valueColor: AlwaysStoppedAnimation(
                      holdHoursLeft < 24
                          ? AppColors.warm
                          : AppColors.limeDeep,
                    ),
                  ),
                ),
                const SizedBox(height: 5),
                Text(
                  holdHoursLeft < 24
                      ? 'Выцветает: осталось ${holdHoursLeft.round()} ч'
                      : 'Прочность: ещё ${(holdHoursLeft / 24).floor()} дн '
                          'удержания',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: holdHoursLeft < 24
                        ? AppColors.warm
                        : AppColors.accentInk,
                  ),
                ),
                const SizedBox(height: 6),
              ],
              if (protected) ...[
                Text(
                  'Под защитой ещё ${holdHoursLeft.round()} ч',
                  style: TextStyle(
                    fontSize: 13.5,
                    fontWeight: FontWeight.w700,
                    color: AppColors.accentInk,
                  ),
                ),
                const SizedBox(height: 6),
              ],
              Text(
                note,
                style: TextStyle(
                  fontSize: 14,
                  height: 1.45,
                  color: AppColors.muted,
                ),
              ),
              if (rel != TerritoryRel.mine && rel != TerritoryRel.club) ...[
                const SizedBox(height: 16),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    onPressed: () {
                      Navigator.of(sheetContext).pop();
                      context.go('/run');
                    },
                    child: const Text('Бежать за ним'),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Color _fill(ZoneOwner owner, {bool flash = false}) {
    if (flash) return AppColors.warning.withValues(alpha: 0.42);
    return switch (owner) {
      ZoneOwner.mine => AppColors.hexOwned.withValues(alpha: 0.22),
      ZoneOwner.enemy => AppColors.hexEnemy.withValues(alpha: 0.18),
      ZoneOwner.club => AppColors.teal.withValues(alpha: 0.20),
      ZoneOwner.free => Colors.transparent,
    };
  }

  Color _border(ZoneOwner owner, {bool flash = false}) {
    if (flash) return AppColors.warning;
    return switch (owner) {
      ZoneOwner.mine => AppColors.hexOwned.withValues(alpha: 0.70),
      ZoneOwner.enemy => AppColors.hexEnemy.withValues(alpha: 0.58),
      ZoneOwner.club => AppColors.teal.withValues(alpha: 0.62),
      ZoneOwner.free => AppColors.zoneNeutral.withValues(alpha: 0.55),
    };
  }

  /// Свежесть удержания 0..1 (168ч = только что захвачен).
  static double _freshness(double? holdHoursLeft) =>
      ((holdHoursLeft ?? 168) / 168).clamp(0.0, 1.0);

  // Реальные территории с сервера — та же палитра; насыщенность = прочность
  // (словарь Ф2: выцветающий квартал видно ещё до потери).
  Color _territoryFill(TerritoryRel rel, {double freshness = 1}) {
    final k = 0.45 + 0.55 * freshness;
    return switch (rel) {
      TerritoryRel.mine => AppColors.hexOwned.withValues(alpha: 0.28 * k),
      TerritoryRel.club => AppColors.teal.withValues(alpha: 0.24 * k),
      TerritoryRel.enemy => AppColors.hexEnemy.withValues(alpha: 0.24 * k),
    };
  }

  Color _territoryBorder(TerritoryRel rel, {double freshness = 1}) {
    final k = 0.5 + 0.5 * freshness;
    return switch (rel) {
      TerritoryRel.mine => AppColors.hexOwned.withValues(alpha: 0.85 * k),
      TerritoryRel.club => AppColors.teal.withValues(alpha: 0.75 * k),
      TerritoryRel.enemy => AppColors.hexEnemy.withValues(alpha: 0.70 * k),
    };
  }
}

// ── Markers ───────────────────────────────────────────────────────────────────

class _MapErrorNotice extends StatelessWidget {
  final VoidCallback onRetry;

  const _MapErrorNotice({required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return _Glass(
      padding: const EdgeInsets.fromLTRB(18, 18, 18, 16),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(CupertinoIcons.wifi_slash, color: AppColors.warning, size: 28),
          const SizedBox(height: 10),
          Text(
            '\u041a\u0430\u0440\u0442\u0430 \u043d\u0435 \u0437\u0430\u0433\u0440\u0443\u0436\u0435\u043d\u0430',
            style: TextStyle(
              color: AppColors.ink,
              fontSize: 17,
              fontWeight: FontWeight.w800,
            ),
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 6),
          Text(
            '\u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0438\u043d\u0442\u0435\u0440\u043d\u0435\u0442 \u0438 \u043d\u0430\u0436\u043c\u0438\u0442\u0435 \u00ab\u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u044c\u00bb.',
            style: TextStyle(color: AppColors.muted, fontSize: 13, height: 1.25),
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 14),
          _NoticeButton(
            label: '\u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u044c',
            icon: CupertinoIcons.arrow_clockwise,
            color: AppColors.graphite,
            onTap: onRetry,
          ),
        ],
      ),
    );
  }
}

class _NoticeButton extends StatelessWidget {
  final String label;
  final IconData icon;
  final Color color;
  final VoidCallback onTap;

  const _NoticeButton({
    required this.label,
    required this.icon,
    required this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        height: 48,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: color,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: AppColors.line),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, color: Colors.white, size: 15),
            const SizedBox(width: 6),
            Text(
              label,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 13,
                fontWeight: FontWeight.w800,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Маркер пользователя, плавно «скользящий» к новой точке между GPS-фиксами.
/// Сглаженная точка приходит из Калмана раз в ~секунду — анимация делает
/// движение метки непрерывным (60fps), без рывков.
class _AnimatedUserMarker extends StatefulWidget {
  final LatLng? target;
  final bool isRunning;
  const _AnimatedUserMarker({required this.target, required this.isRunning});

  @override
  State<_AnimatedUserMarker> createState() => _AnimatedUserMarkerState();
}

class _AnimatedUserMarkerState extends State<_AnimatedUserMarker>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  LatLng? _from;
  LatLng? _to;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 900),
    )..addListener(() => setState(() {}));
    _from = widget.target;
    _to = widget.target;
  }

  @override
  void didUpdateWidget(covariant _AnimatedUserMarker old) {
    super.didUpdateWidget(old);
    final t = widget.target;
    if (t == null) {
      _from = null;
      _to = null;
      return;
    }
    if (_to == null) {
      setState(() {
        _from = t;
        _to = t;
      });
      return;
    }
    if (t.latitude != _to!.latitude || t.longitude != _to!.longitude) {
      _from = _current ?? _to; // стартуем из текущей экранной позиции
      _to = t;
      _controller.forward(from: 0);
    }
  }

  LatLng? get _current {
    if (_from == null || _to == null) return null;
    final v = Curves.easeOut.transform(_controller.value);
    return LatLng(
      _from!.latitude + (_to!.latitude - _from!.latitude) * v,
      _from!.longitude + (_to!.longitude - _from!.longitude) * v,
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = _current;
    if (p == null) return const MarkerLayer(markers: []);
    return MarkerLayer(
      markers: [
        Marker(
          point: p,
          width: 26,
          height: 26,
          child: _UserMarker(isRunning: widget.isRunning),
        ),
      ],
    );
  }
}

class _UserMarker extends StatefulWidget {
  final bool isRunning;
  const _UserMarker({required this.isRunning});

  @override
  State<_UserMarker> createState() => _UserMarkerState();
}

class _UserMarkerState extends State<_UserMarker>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;
  late final Animation<double> _scale;
  late final Animation<double> _opacity;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      duration: const Duration(milliseconds: 1600),
      vsync: this,
    )..repeat();
    _scale = Tween<double>(
      begin: 1.0,
      end: 2.6,
    ).animate(CurvedAnimation(parent: _ctrl, curve: Curves.easeOut));
    _opacity = Tween<double>(
      begin: 0.6,
      end: 0.0,
    ).animate(CurvedAnimation(parent: _ctrl, curve: Curves.easeOut));
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.isRunning ? AppColors.success : AppColors.electricBlue;
    return Stack(
      alignment: Alignment.center,
      children: [
        // Пульсирующее кольцо
        AnimatedBuilder(
          animation: _ctrl,
          builder: (_, __) => Opacity(
            opacity: _opacity.value,
            child: Transform.scale(
              scale: _scale.value,
              child: Container(
                width: 26,
                height: 26,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  border: Border.all(color: c, width: 2),
                ),
              ),
            ),
          ),
        ),
        // Основная точка
        Container(
          width: 26,
          height: 26,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: c.withValues(alpha: 0.22),
            border: Border.all(color: c, width: 2),
          ),
        ),
        Container(
          width: 10,
          height: 10,
          decoration: BoxDecoration(shape: BoxShape.circle, color: c),
        ),
      ],
    );
  }
}

class _RoutePointMarker extends StatelessWidget {
  final String label;
  final Color color;
  final IconData icon;

  const _RoutePointMarker({
    required this.label,
    required this.color,
    required this.icon,
  });

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: label,
      child: Container(
        width: 30,
        height: 30,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: Colors.black.withValues(alpha: 0.76),
          border: Border.all(color: color, width: 2),
          boxShadow: [
            BoxShadow(
              color: color.withValues(alpha: 0.28),
              blurRadius: 10,
              spreadRadius: 1,
            ),
          ],
        ),
        child: Icon(icon, color: color, size: 13),
      ),
    );
  }
}

// ── Frosted glass ─────────────────────────────────────────────────────────────

class _Glass extends StatelessWidget {
  final Widget child;
  final BorderRadius borderRadius;
  final EdgeInsetsGeometry? padding;

  const _Glass({
    required this.child,
    this.borderRadius = const BorderRadius.all(Radius.circular(18)),
    this.padding,
  });

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: borderRadius,
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 14, sigmaY: 14),
        child: Container(
          padding: padding,
          decoration: BoxDecoration(
            color: AppColors.glass,
            borderRadius: borderRadius,
            border: Border.all(color: AppColors.line),
          ),
          child: child,
        ),
      ),
    );
  }
}

// ── Top bar ───────────────────────────────────────────────────────────────────

class _KvartalTopLogo extends StatelessWidget {
  const _KvartalTopLogo();

  @override
  Widget build(BuildContext context) {
    return _Glass(
      padding: EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          KvartalLogoBadge(size: 24),
          SizedBox(height: 4),
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                '\u0433\u043e\u0440\u043e\u0434 ',
                style: TextStyle(
                  color: AppColors.faint,
                  fontSize: 9,
                  fontWeight: FontWeight.w700,
                  height: 1,
                ),
              ),
              Text(
                '\u042f\u043a\u0443\u0442\u0441\u043a',
                style: TextStyle(
                  color: AppColors.ink,
                  fontSize: 10,
                  fontWeight: FontWeight.w800,
                  height: 1,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// Чип погоды: реальные данные Open-Meteo (температура + иконка состояния).
/// Тап → подробное мини-окно (ветер, осадки, влажность).
/// Морозный бонус к баллам тут НЕ показывается — это отдельная фича (D-20).
class _WeatherChip extends ConsumerWidget {
  const _WeatherChip();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(weatherProvider);
    final w = async.valueOrNull;
    final tempText = async.when(
      data: (d) => formatTemp(d.tempC),
      loading: () => '…',
      error: (_, __) => '—',
    );
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () => showWeatherDetailSheet(context),
      child: _Glass(
        // Поля подобраны так, чтобы высота дотягивала до нормы 48 dp.
        padding: EdgeInsets.symmetric(horizontal: 12, vertical: 16),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              w == null
                  ? CupertinoIcons.cloud
                  : weatherIcon(w.weatherCode, isNight: isNightNow()),
              size: 13,
              color: AppColors.info,
            ),
            SizedBox(width: 5),
            Text(
              tempText,
              style: Theme.of(
                context,
              ).textTheme.labelMedium?.copyWith(color: AppColors.ink),
            ),
            SizedBox(width: 4),
            Icon(
              CupertinoIcons.chevron_down,
              size: 10,
              color: AppColors.textTertiary,
            ),
          ],
        ),
      ),
    );
  }
}

// ── Legend ────────────────────────────────────────────────────────────────────

class _CollapsibleLegend extends StatelessWidget {
  final bool open;
  final VoidCallback onToggle;
  const _CollapsibleLegend({required this.open, required this.onToggle});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onToggle,
      behavior: HitTestBehavior.opaque,
      child: AnimatedSize(
        duration: const Duration(milliseconds: 220),
        curve: Curves.easeOutCubic,
        alignment: Alignment.topLeft,
        child: open
            ? _Legend()
            // Свёрнутая: компактная плитка 2×2 цветов словаря.
            : _Glass(
                padding: const EdgeInsets.all(7),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        _dot(AppColors.hexOwned),
                        const SizedBox(width: 3),
                        _dot(AppColors.teal),
                      ],
                    ),
                    const SizedBox(height: 3),
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        _dot(AppColors.hexEnemy),
                        const SizedBox(width: 3),
                        _dot(AppColors.zoneNeutral),
                      ],
                    ),
                  ],
                ),
              ),
      ),
    );
  }

  Widget _dot(Color c) => Container(
        width: 7,
        height: 7,
        decoration: BoxDecoration(color: c, shape: BoxShape.circle),
      );
}

class _Legend extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return _Glass(
      padding: EdgeInsets.symmetric(horizontal: 8, vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          _LegendDot(color: AppColors.hexOwned, label: 'Моё'),
          SizedBox(height: 3),
          _LegendDot(color: AppColors.teal, label: 'Клуба'),
          SizedBox(height: 3),
          _LegendDot(color: AppColors.hexEnemy, label: 'Чужое'),
          SizedBox(height: 3),
          _LegendDot(color: AppColors.zoneNeutral, label: 'Ничьё'),
        ],
      ),
    );
  }
}

class _LegendDot extends StatelessWidget {
  final Color color;
  final String label;
  const _LegendDot({required this.color, required this.label});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 7,
          height: 7,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        const SizedBox(width: 5),
        Text(label, style: TextStyle(color: AppColors.ink, fontSize: 10)),
      ],
    );
  }
}

// ── Buttons ───────────────────────────────────────────────────────────────────

class _IconBtn extends StatelessWidget {
  final IconData icon;
  final Color color;
  final VoidCallback onTap;
  const _IconBtn({
    required this.icon,
    required this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: _Glass(
        borderRadius: const BorderRadius.all(Radius.circular(18)),
        padding: const EdgeInsets.all(8),
        child: Icon(icon, color: color, size: 18),
      ),
    );
  }
}

// ── Bottom panel ──────────────────────────────────────────────────────────────

class _BottomPanel extends StatelessWidget {
  final RunState runState;
  final List<ServerTerritory> territories;
  final LoopClosureStatus closureStatus;

  const _BottomPanel({
    required this.runState,
    required this.territories,
    required this.closureStatus,
  });

  @override
  Widget build(BuildContext context) {
    final isRunning = runState.status != RunStatus.idle;
    // Счёт по СЕРВЕРНЫМ территориям — раньше панель считала демо-сетку
    // и показывала «Мои 0» при живой зоне («Идеальный маршрут», 03.09).
    final mine =
        territories.where((t) => t.rel == TerritoryRel.mine).length;
    final enemy =
        territories.where((t) => t.rel == TerritoryRel.enemy).length;
    final club =
        territories.where((t) => t.rel == TerritoryRel.club).length;

    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 0, 12, 10),
      child: _Glass(
        padding: EdgeInsets.symmetric(
          horizontal: 12,
          vertical: isRunning ? 12 : 7,
        ),
        child: isRunning
            ? Row(
                children: [
                  _Stat(
                    label: 'Дистанция',
                    value: '${runState.distanceKm.toStringAsFixed(2)} км',
                  ),
                  _Div(),
                  _Stat(label: 'Время', value: runState.elapsedFormatted),
                  _Div(),
                  _Stat(
                    label: 'До старта',
                    value: runState.route.length < 2
                        ? '-- м'
                        : '${closureStatus.gapMeters.round()} м',
                  ),
                ],
              )
            : Row(
                children: [
                  _Stat(
                    label: 'Мои',
                    value: '$mine',
                    icon: CupertinoIcons.hexagon,
                    color: AppColors.hexOwned,
                    compact: true,
                  ),
                  _Div(),
                  _Stat(
                    label: 'Чужих',
                    value: '$enemy',
                    icon: CupertinoIcons.flag,
                    color: AppColors.hexEnemy,
                    compact: true,
                  ),
                  _Div(),
                  _Stat(
                    label: 'Клуб',
                    value: '$club',
                    icon: CupertinoIcons.person_2,
                    color: AppColors.teal,
                    compact: true,
                  ),
                ],
              ),
      ),
    );
  }
}

class _Stat extends StatelessWidget {
  final String label, value;
  final IconData? icon;
  final Color? color;

  /// Компактный режим (счётчики зон): панель ниже — карту видно больше.
  final bool compact;
  const _Stat({
    required this.label,
    required this.value,
    this.icon,
    this.color,
    this.compact = false,
  });

  @override
  Widget build(BuildContext context) {
    final c = color ?? AppColors.ink;
    if (compact) {
      // Одна строка: иконка · число · подпись.
      return Expanded(
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            if (icon != null) ...[
              Icon(icon, size: 14, color: c),
              const SizedBox(width: 6),
            ],
            Text(
              value,
              style: TextStyle(
                fontFamily: AppTheme.fontDisplay,
                fontSize: 15,
                fontWeight: FontWeight.w800,
                color: c,
              ),
            ),
            const SizedBox(width: 5),
            Text(
              label,
              style: TextStyle(fontSize: 11.5, color: AppColors.muted),
            ),
          ],
        ),
      );
    }
    return Expanded(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 18, color: c),
            const SizedBox(height: 4),
          ],
          Text(
            value,
            style: Theme.of(context).textTheme.titleLarge?.copyWith(color: c),
          ),
          Text(label, style: Theme.of(context).textTheme.bodySmall),
        ],
      ),
    );
  }
}

class _Div extends StatelessWidget {
  @override
  Widget build(BuildContext context) =>
      Container(width: 1, height: 36, color: AppColors.bgElevated);
}

// ── Блок «Сегодня» (Ф2 «Карта-дом») ──────────────────────────────────────────

class _TodayRow extends ConsumerWidget {
  const _TodayRow();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final weather = ref.watch(weatherProvider).valueOrNull;
    final win = bestRunWindow(weather?.hourly ?? const []);
    final level = ref.watch(runnerLevelProvider).valueOrNull;
    final me = ref.watch(leagueBoardDataProvider).valueOrNull?.me;
    final form = ref.watch(weekFormProvider);
    final days = form.where((d) => d).length;

    // Кламп масштаба текста: на телефонах с крупным шрифтом карточки не рвёт.
    return MediaQuery.withClampedTextScaling(
      maxScaleFactor: 1.0,
      child: SizedBox(
      height: 62,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(14, 4, 14, 6),
        children: [
          if (win != null)
            _TodayCard(
              icon: CupertinoIcons.timer,
              title: 'Окно бега',
              value:
                  '${win.start.hour}:00–${win.end.hour}:00',
              onTap: () => showWeatherDetailSheet(context),
            ),
          _TodayCard(
            icon: CupertinoIcons.chart_bar_alt_fill,
            title: 'Дивизион',
            value: [
              if (level != null) level.title,
              if (me?.place != null) '#${me!.place}',
            ].join(' · ').isEmpty
                ? 'загрузка…'
                : [
                    if (level != null) level.title,
                    if (me?.place != null) '#${me!.place}',
                  ].join(' · '),
            onTap: () => context.go('/leaderboard'),
          ),
          _TodayCard(
            icon: CupertinoIcons.calendar,
            title: 'Неделя',
            value: '$days из 7 дней',
            onTap: () => context.go('/leaderboard'),
          ),
        ],
      ),
      ),
    );
  }
}

class _TodayCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String value;
  final VoidCallback onTap;

  const _TodayCard({
    required this.icon,
    required this.title,
    required this.value,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: GestureDetector(
        onTap: onTap,
        child: _Glass(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 15, color: AppColors.accentInk),
              const SizedBox(width: 8),
              Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title.toUpperCase(),
                    style: TextStyle(
                      fontSize: 8.5,
                      fontWeight: FontWeight.w700,
                      letterSpacing: .6,
                      color: AppColors.faint,
                    ),
                  ),
                  Text(
                    value,
                    style: TextStyle(
                      fontSize: 12.5,
                      fontWeight: FontWeight.w800,
                      color: AppColors.ink,
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
