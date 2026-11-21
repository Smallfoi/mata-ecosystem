import 'dart:math' show pow;

import 'package:dio/dio.dart';

import '../../../core/api/api_client.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';

import '../../map/data/location_provider.dart';

/// Один час прогноза — для «лучшего времени пробежки» (дизайн 2026-08-21).
class HourForecast {
  final DateTime timeLocal;
  final double tempC;
  final double feelsLikeC;
  final double windKmh;
  final int precipProbPct;
  final double precipMm;
  final int wmo;

  const HourForecast({
    required this.timeLocal,
    required this.tempC,
    required this.feelsLikeC,
    required this.windKmh,
    required this.precipProbPct,
    required this.precipMm,
    required this.wmo,
  });
}

/// Текущая погода для точки (реальные данные MET Norway).
/// Морозный коэффициент к баллам тут НЕ считается — это отдельная фича (D-20).
class WeatherData {
  final double tempC;
  final double feelsLikeC;
  final double windSpeedKmh;
  final int windDirDeg;
  final int precipProbabilityPct;
  final int humidityPct;
  final int weatherCode; // WMO weather code (маппим из symbol_code met.no)
  final List<HourForecast> hourly; // почасовой ряд (до ~24 ч, с текущего часа)

  const WeatherData({
    required this.tempC,
    required this.feelsLikeC,
    required this.windSpeedKmh,
    required this.windDirDeg,
    required this.precipProbabilityPct,
    required this.humidityPct,
    required this.weatherCode,
    this.hourly = const [],
  });
}

// MET Norway (api.met.no): бесплатно, без ключа, коммерческое использование
// разрешено (CC-BY 4.0) и — главное — РЕАЛЬНО доступен из РФ. Заменил Open-Meteo
// (D-20), который из РФ не грузился (соединение висло) и был только non-commercial.
// Требования met.no: осмысленный User-Agent с контактом, координаты ≤4 знаков,
// не частить (кэш на стороне провайдера ~раз в час). Зовём напрямую с клиента.
const _metNoUrl =
    'https://api.met.no/weatherapi/locationforecast/2.0/compact';

/// Общий клиент: пул соединений и таймауты (раньше — новый Dio без connectTimeout
/// на каждый запрос: при плохой сети запрос мог висеть бесконечно).
final _weatherDio = ApiClient.create(headers: const {});

Future<WeatherData> _fetchWeather(LatLng at) async {
  final res = await _weatherDio.get<Map<String, dynamic>>(
    _metNoUrl,
    queryParameters: {
      'lat': at.latitude.toStringAsFixed(4),
      'lon': at.longitude.toStringAsFixed(4),
    },
    options: Options(
      receiveTimeout: const Duration(seconds: 15),
      // met.no без User-Agent с контактом блокирует запрос (403).
      headers: const {
        'User-Agent': 'MATA-Kvartal/1.0 (github.com/Smallfoi/mata-ecosystem)',
      },
    ),
  );

  final series =
      (res.data?['properties']?['timeseries'] as List?) ?? const [];
  if (series.isEmpty) {
    return const WeatherData(
      tempC: 0,
      feelsLikeC: 0,
      windSpeedKmh: 0,
      windDirDeg: 0,
      precipProbabilityPct: 0,
      humidityPct: 0,
      weatherCode: 0,
    );
  }

  final data0 =
      ((series.first as Map<String, dynamic>)['data'] as Map<String, dynamic>?) ??
          const {};
  final details =
      (data0['instant']?['details'] as Map<String, dynamic>?) ?? const {};
  final next1 = (data0['next_1_hours'] as Map<String, dynamic>?) ?? const {};
  final next1Details =
      (next1['details'] as Map<String, dynamic>?) ?? const {};
  final symbol = (next1['summary']?['symbol_code'] as String?) ?? '';

  final temp = (details['air_temperature'] as num?)?.toDouble() ?? 0;
  final windKmh = ((details['wind_speed'] as num?)?.toDouble() ?? 0) * 3.6;

  return WeatherData(
    tempC: temp,
    feelsLikeC: _windChill(temp, windKmh),
    windSpeedKmh: windKmh,
    windDirDeg: (details['wind_from_direction'] as num?)?.round() ?? 0,
    precipProbabilityPct:
        (next1Details['probability_of_precipitation'] as num?)?.round() ?? 0,
    humidityPct: (details['relative_humidity'] as num?)?.round() ?? 0,
    weatherCode: _wmoFromSymbol(symbol),
    hourly: _parseHourly(series),
  );
}

/// Почасовой ряд из timeseries met.no: первые ~24 записи с next_1_hours
/// (дальше провайдер отдаёт 6-часовые шаги — они для окна не нужны).
List<HourForecast> _parseHourly(List<dynamic> series) {
  final out = <HourForecast>[];
  for (final raw in series) {
    if (out.length >= 24) break;
    final entry = raw as Map<String, dynamic>;
    final data = (entry['data'] as Map<String, dynamic>?) ?? const {};
    final next1 = data['next_1_hours'] as Map<String, dynamic>?;
    if (next1 == null) continue; // почасовые кончились
    final time = DateTime.tryParse((entry['time'] as String?) ?? '');
    if (time == null) continue;
    final details =
        (data['instant']?['details'] as Map<String, dynamic>?) ?? const {};
    final n1d = (next1['details'] as Map<String, dynamic>?) ?? const {};
    final t = (details['air_temperature'] as num?)?.toDouble() ?? 0;
    final wind = ((details['wind_speed'] as num?)?.toDouble() ?? 0) * 3.6;
    out.add(HourForecast(
      timeLocal: time.toLocal(),
      tempC: t,
      feelsLikeC: _windChill(t, wind),
      windKmh: wind,
      precipProbPct:
          (n1d['probability_of_precipitation'] as num?)?.round() ?? 0,
      precipMm: (n1d['precipitation_amount'] as num?)?.toDouble() ?? 0,
      wmo: _wmoFromSymbol(
          (next1['summary']?['symbol_code'] as String?) ?? ''),
    ));
  }
  return out;
}

/// «Ощущается как» — ветрохолодовой индекс (важно бегунам в мороз). Формула
/// Канады применима при T≤10°C и ветре ≥4.8 км/ч; иначе ≈ температура.
double _windChill(double tempC, double windKmh) {
  if (tempC > 10 || windKmh < 4.8) return tempC;
  final v = pow(windKmh, 0.16).toDouble();
  return 13.12 + 0.6215 * tempC - 11.37 * v + 0.3965 * tempC * v;
}

/// MET Norway `symbol_code` ("partlycloudy_day", "lightsnow", …) → ближайший
/// WMO-код, чтобы существующий UI (`weatherIcon`/`weatherLabel` по WMO) работал
/// без изменений.
int _wmoFromSymbol(String symbol) {
  final s = symbol.split('_').first; // отбрасываем _day/_night/_polartwilight
  if (s == 'clearsky') return 0;
  if (s == 'fair') return 1;
  if (s == 'partlycloudy') return 2;
  if (s == 'cloudy') return 3;
  if (s.contains('fog')) return 45;
  if (s.contains('thunder')) return 95;
  if (s.contains('sleet')) return 66;
  if (s.contains('snow')) return 71;
  if (s.contains('rainshowers') || s.contains('heavyrain')) return 80;
  if (s.contains('drizzle')) return 51;
  if (s.contains('rain')) return 61;
  return 3; // по умолчанию — облачно
}

/// Погода по позиции игрока (если нет — центр Якутска).
/// НЕ блокируемся на GPS (`getCurrentPosition` без таймаута может висеть → погода
/// вечно «…») и НЕ `watch`-им стрим (иначе перезапуск на каждый GPS-тик). Берём
/// НЕблокирующий снимок: есть позиция — по ней, нет — центр Якутска (погоде
/// хватает координат уровня города).
final weatherProvider = FutureProvider.autoDispose<WeatherData>((ref) async {
  final snapshot = ref.read(positionStreamProvider).valueOrNull;
  final pos = snapshot?.toLatLng ?? yakutskCenter;
  return _fetchWeather(pos);
});
