import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_colors.dart';
import '../data/weather_provider.dart';
import '../domain/run_window.dart';
import 'weather_background.dart';

// ── WMO weather code → иконка / подпись ──────────────────────────────────────

IconData weatherIcon(int code, {bool isNight = false}) {
  if (code == 0) {
    return isNight
        ? CupertinoIcons.moon_stars_fill
        : CupertinoIcons.sun_max_fill;
  }
  if (code <= 2) {
    return isNight
        ? CupertinoIcons.cloud_moon_fill
        : CupertinoIcons.cloud_sun_fill;
  }
  if (code == 3) return CupertinoIcons.cloud_fill;
  if (code == 45 || code == 48) return CupertinoIcons.cloud_fog_fill;
  if (code >= 51 && code <= 57) return CupertinoIcons.cloud_drizzle_fill;
  if (code >= 61 && code <= 67) return CupertinoIcons.cloud_rain_fill;
  if (code >= 71 && code <= 77) return CupertinoIcons.snow;
  if (code >= 80 && code <= 82) return CupertinoIcons.cloud_heavyrain_fill;
  if (code == 85 || code == 86) return CupertinoIcons.snow;
  if (code >= 95) return CupertinoIcons.cloud_bolt_fill;
  return CupertinoIcons.cloud_fill;
}

String weatherLabel(int code) {
  if (code == 0) return 'Ясно';
  if (code == 1) return 'Малооблачно';
  if (code == 2) return 'Переменная облачность';
  if (code == 3) return 'Пасмурно';
  if (code == 45 || code == 48) return 'Туман';
  if (code >= 51 && code <= 55) return 'Морось';
  if (code == 56 || code == 57) return 'Ледяная морось';
  if (code >= 61 && code <= 65) return 'Дождь';
  if (code == 66 || code == 67) return 'Ледяной дождь';
  if (code >= 71 && code <= 77) return 'Снег';
  if (code >= 80 && code <= 82) return 'Ливень';
  if (code == 85 || code == 86) return 'Снегопад';
  if (code == 95) return 'Гроза';
  if (code >= 96) return 'Гроза с градом';
  return '—';
}

String windCompass(int deg) {
  const points = ['С', 'СВ', 'В', 'ЮВ', 'Ю', 'ЮЗ', 'З', 'СЗ'];
  return points[(((deg + 22.5) ~/ 45) % 8)];
}

String formatTemp(double t) => '${t.round()}°C';

// ── Мини-окно с подробной погодой (по тапу на чип) ───────────────────────────

Future<void> showWeatherDetailSheet(BuildContext context) {
  return showModalBottomSheet<void>(
    context: context,
    backgroundColor: Colors.transparent,
    // Контент вырос (блок «Лучшее время для пробежки») — шторка скроллится,
    // а не режет его фиксированной половиной экрана.
    isScrollControlled: true,
    builder: (_) => const _WeatherDetailSheet(),
  );
}

class _WeatherDetailSheet extends ConsumerWidget {
  const _WeatherDetailSheet();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(weatherProvider);
    return Container(
      constraints: BoxConstraints(
        maxHeight: MediaQuery.of(context).size.height * 0.86,
      ),
      decoration: BoxDecoration(
        color: AppColors.bgSurface,
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      padding: const EdgeInsets.fromLTRB(20, 10, 20, 24),
      child: SafeArea(
        top: false,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Center(
                child: Container(
                  width: 40,
                  height: 4,
                  margin: const EdgeInsets.only(bottom: 16),
                  decoration: BoxDecoration(
                    color: AppColors.separator,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              Row(
                children: [
                  Text(
                    'Погода',
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      color: AppColors.textPrimary,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const Spacer(),
                  IconButton(
                    visualDensity: VisualDensity.compact,
                    icon: Icon(
                      CupertinoIcons.refresh,
                      size: 18,
                      color: AppColors.textSecondary,
                    ),
                    onPressed: () => ref.invalidate(weatherProvider),
                  ),
                ],
              ),
              const SizedBox(height: 4),
              async.when(
                loading: () => Padding(
                  padding: EdgeInsets.symmetric(vertical: 28),
                  child: Center(
                    child: CircularProgressIndicator(
                      color: AppColors.electricBlue,
                    ),
                  ),
                ),
                error: (_, __) => Padding(
                  padding: EdgeInsets.symmetric(vertical: 20),
                  child: Text(
                    'Не удалось загрузить погоду.\nПроверь интернет и попробуй обновить.',
                    style: TextStyle(color: AppColors.textSecondary),
                  ),
                ),
                data: (w) => _WeatherBody(w),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _WeatherBody extends StatelessWidget {
  final WeatherData w;
  const _WeatherBody(this.w);

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Живой анимированный баннер-«штрих» по текущему условию (солнце/облака/
        // дождь/снег/туман/гроза). Текст поверх — белый с тенью для контраста.
        // 164 (было 150): контент с крупным шрифтом устройства переполнял
        // баннер на ~5px («BOTTOM OVERFLOWED», замечание владельца 2026-08-21).
        ClipRRect(
          borderRadius: BorderRadius.circular(16),
          child: SizedBox(
            height: 164,
            child: Stack(
              fit: StackFit.expand,
              children: [
                WeatherBackground(weatherCode: w.weatherCode, height: 164),
                // Скрим: нижняя треть сцены всегда затемнена — температура и
                // условие читаются сразу на любом небе (замечание владельца).
                const DecoratedBox(
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      begin: Alignment.topCenter,
                      end: Alignment.bottomCenter,
                      stops: [0.34, 0.62, 1.0],
                      colors: [
                        Color(0x000D1319),
                        Color(0x470D1319),
                        Color(0x940D1319),
                      ],
                    ),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 14, 16, 12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisAlignment: MainAxisAlignment.end,
                    children: [
                      // Иконку убрали: основной визуал — живой анимированный фон
                      // (солнце/луна по времени и фазе, облака, дождь, снег, гроза).
                      Text(
                        formatTemp(w.tempC),
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 46,
                          height: 1.0,
                          fontWeight: FontWeight.w400,
                          letterSpacing: -2,
                          shadows: [
                            Shadow(
                              color: Color(0x73081014),
                              blurRadius: 3,
                              offset: Offset(0, 1),
                            ),
                            Shadow(
                              color: Color(0x59081014),
                              blurRadius: 14,
                              offset: Offset(0, 4),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        weatherLabel(w.weatherCode),
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 15,
                          fontWeight: FontWeight.w600,
                          shadows: [
                            Shadow(color: Color(0x80081014), blurRadius: 6),
                          ],
                        ),
                      ),
                      const SizedBox(height: 1),
                      Text(
                        'Ощущается как ${formatTemp(w.feelsLikeC)}',
                        style: const TextStyle(
                          color: Color(0xF2FFFFFF),
                          fontSize: 12.5,
                          shadows: [
                            Shadow(color: Color(0x80081014), blurRadius: 6),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 18),
        Row(
          children: [
            _StatTile(
              icon: CupertinoIcons.wind,
              label: 'Ветер',
              value:
                  '${w.windSpeedKmh.round()} км/ч · ${windCompass(w.windDirDeg)}',
            ),
            _StatTile(
              icon: CupertinoIcons.cloud_rain,
              label: 'Осадки',
              value: '${w.precipProbabilityPct}%',
            ),
            _StatTile(
              icon: CupertinoIcons.drop,
              label: 'Влажность',
              value: '${w.humidityPct}%',
            ),
          ],
        ),
        if (w.hourly.length >= 2) ...[
          const SizedBox(height: 18),
          _BestRunBlock(hourly: w.hourly),
        ],
        const SizedBox(height: 18),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            color: AppColors.bgElevated,
            borderRadius: BorderRadius.circular(12),
          ),
          child: Row(
            children: [
              Icon(CupertinoIcons.snow, size: 16, color: AppColors.info),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'Морозный бонус к баллам за бег в холод — скоро',
                  style: TextStyle(
                    color: AppColors.textSecondary.withValues(alpha: 0.9),
                    fontSize: 12,
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// «Лучшее время для пробежки»: почасовой таймлайн с оценкой каждого часа
/// и окно-бейдж (дизайн-проект погоды, утверждён 2026-08-21).
class _BestRunBlock extends StatelessWidget {
  final List<HourForecast> hourly;
  const _BestRunBlock({required this.hourly});

  @override
  Widget build(BuildContext context) {
    final window = bestRunWindow(hourly);
    if (window == null) return SizedBox.shrink();
    final hours = hourly.take(18).toList();

    String hh(DateTime t) => t.hour.toString().padLeft(2, '0');

    return Container(
      padding: EdgeInsets.fromLTRB(14, 12, 14, 14),
      decoration: BoxDecoration(
        color: AppColors.bgElevated,
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.directions_run, size: 16, color: AppColors.accentInk),
              SizedBox(width: 7),
              Text(
                'Лучшее время для пробежки',
                style: TextStyle(
                  color: AppColors.textPrimary,
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          SizedBox(
            height: 46,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                for (final h in hours)
                  Expanded(
                    child: Builder(
                      builder: (_) {
                        final score = runScore(h);
                        final inWindow =
                            !h.timeLocal.isBefore(window.start) &&
                            h.timeLocal.isBefore(window.end);
                        return Container(
                          height: 8 + 38 * score / 100,
                          margin: const EdgeInsets.symmetric(horizontal: 1.5),
                          decoration: BoxDecoration(
                            color: inWindow
                                ? AppColors.lime
                                : score >= 55
                                ? AppColors.lime.withValues(alpha: 0.35)
                                : AppColors.separator,
                            border: inWindow
                                ? Border.all(
                                    color: const Color(0xFFB9CC3D),
                                    width: 1,
                                  )
                                : null,
                            borderRadius: const BorderRadius.vertical(
                              top: Radius.circular(3),
                            ),
                          ),
                        );
                      },
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 4),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              for (var i = 0; i < hours.length; i += 3)
                Text(
                  hh(hours[i].timeLocal),
                  style: TextStyle(
                    color: AppColors.textTertiary,
                    fontSize: 9.5,
                  ),
                ),
            ],
          ),
          const SizedBox(height: 10),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              color: AppColors.graphite,
              borderRadius: BorderRadius.circular(9),
            ),
            // Wrap вместо Row: на узких экранах/крупном шрифте условия переносятся
            // на вторую строку целиком — никакого «…» (замечание владельца).
            child: Wrap(
              crossAxisAlignment: WrapCrossAlignment.center,
              spacing: 8,
              runSpacing: 3,
              children: [
                Text(
                  '${hh(window.start)}:00–${hh(window.end)}:00',
                  style: const TextStyle(
                    color: AppColors.lime,
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                Text(
                  window.summary,
                  style: const TextStyle(
                    color: Color(0xFFC9CDC2),
                    fontSize: 12.5,
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

class _StatTile extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;

  const _StatTile({
    required this.icon,
    required this.label,
    required this.value,
  });

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 18, color: AppColors.textSecondary),
          const SizedBox(height: 6),
          Text(
            label,
            style: TextStyle(color: AppColors.textTertiary, fontSize: 11),
          ),
          const SizedBox(height: 2),
          Text(
            value,
            style: TextStyle(
              color: AppColors.textPrimary,
              fontSize: 13,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}
