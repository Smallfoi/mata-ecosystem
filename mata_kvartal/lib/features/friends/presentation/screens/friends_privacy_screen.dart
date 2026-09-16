import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../map/data/location_provider.dart';
import '../../data/friends_provider.dart';

/// Приватность карты друзей (D-83, 2c). По умолчанию тебя не видит никто.
/// Управляет видимостью, «Тенью» (скрыться с таймером, взаимно) и зоной дома.
class FriendsPrivacyScreen extends ConsumerWidget {
  const FriendsPrivacyScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final prefs = ref.watch(friendPrefsProvider).valueOrNull ?? const FriendMapPrefs();
    final act = ref.read(friendsActionsProvider);

    return Scaffold(
      backgroundColor: AppColors.bg,
      appBar: AppBar(
        backgroundColor: AppColors.bg,
        elevation: 0,
        title: const Text('Приватность',
            style: TextStyle(fontWeight: FontWeight.w800, fontSize: 19)),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 32),
        children: [
          Text('Друзья на карте. Меняешь только ты.',
              style: TextStyle(color: AppColors.muted, fontSize: 13)),
          const SizedBox(height: 16),

          _Card(children: [
            _ToggleRow(
              label: 'Показывать меня друзьям',
              desc: 'Дружба взаимная. Незнакомцы не видят твою точку никогда.',
              value: prefs.visible,
              onChanged: (v) => act.updatePrefs({'visible': v}),
            ),
          ]),
          const SizedBox(height: 12),

          _Card(children: [
            Text('ТОЧНОСТЬ',
                style: _labelStyle),
            const SizedBox(height: 8),
            Row(children: [
              Icon(CupertinoIcons.hexagon, size: 18, color: AppColors.lime),
              const SizedBox(width: 10),
              Expanded(
                child: Text('До гекса (~150 м) — район, не адрес. Точную точку не передаём.',
                    style: TextStyle(color: AppColors.ink, fontSize: 13, height: 1.4)),
              ),
            ]),
          ]),
          const SizedBox(height: 12),

          // ── Тень ──
          _Card(children: [
            Text('ТЕНЬ — СКРЫТЬСЯ НА ВРЕМЯ', style: _labelStyle),
            const SizedBox(height: 4),
            Text('Пока в тени: тебя не видно, и ты не видишь друзей.',
                style: TextStyle(color: AppColors.muted, fontSize: 12, height: 1.4)),
            const SizedBox(height: 12),
            if (prefs.inShadow)
              Row(children: [
                Icon(CupertinoIcons.eye_slash_fill, size: 18, color: AppColors.lime),
                const SizedBox(width: 8),
                Expanded(
                  child: Text('В тени до ${_hhmm(prefs.hideUntil)}',
                      style: TextStyle(
                          color: AppColors.ink, fontSize: 14, fontWeight: FontWeight.w700)),
                ),
                _Btn('Выйти', primary: true,
                    onTap: () => act.updatePrefs({'hideHours': 0})),
              ])
            else
              Row(children: [
                for (final h in const [2, 8, 24]) ...[
                  Expanded(
                    child: _Btn('$h ч',
                        onTap: () => act.updatePrefs({'hideHours': h})),
                  ),
                  if (h != 24) const SizedBox(width: 8),
                ],
              ]),
          ]),
          const SizedBox(height: 12),

          // ── Зона дома ──
          _Card(children: [
            _ToggleRow(
              label: 'Скрывать точку у дома',
              desc: 'Возле дома точка прячется — адрес не выдаётся.',
              value: prefs.homeHidden,
              onChanged: (v) => act.updatePrefs({'homeHidden': v}),
            ),
            const SizedBox(height: 12),
            Row(children: [
              Expanded(
                child: _Btn(prefs.homeSet ? 'Дом задан · обновить' : 'Задать дом здесь',
                    onTap: () {
                  final p = ref.read(positionStreamProvider).valueOrNull?.toLatLng;
                  if (p == null) {
                    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                        content: Text('Нет геопозиции — включи её и попробуй снова')));
                    return;
                  }
                  act.updatePrefs({'home': {'lat': p.latitude, 'lng': p.longitude}});
                  ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('Дом сохранён по текущему месту')));
                }),
              ),
              if (prefs.homeSet) ...[
                const SizedBox(width: 8),
                _Btn('Сбросить', onTap: () => act.updatePrefs({'home': null})),
              ],
            ]),
          ]),
          const SizedBox(height: 16),

          Text(
            '🔒 Геопозиция — персональные данные (152-ФЗ). Собираем только пока открыта карта, огрублённо, и делимся лишь со взаимными друзьями. Live-слой — с 16 лет.',
            style: TextStyle(color: AppColors.faint, fontSize: 11.5, height: 1.5),
          ),
        ],
      ),
    );
  }

  static String _hhmm(DateTime? d) {
    if (d == null) return '';
    final l = d.toLocal();
    return '${l.hour.toString().padLeft(2, '0')}:${l.minute.toString().padLeft(2, '0')}';
  }

  static final _labelStyle = TextStyle(
      color: AppColors.muted,
      fontSize: 11.5,
      fontWeight: FontWeight.w700,
      letterSpacing: .6);
}

class _Card extends StatelessWidget {
  final List<Widget> children;
  const _Card({required this.children});
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: AppColors.paper,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: AppColors.line),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: children),
      );
}

class _ToggleRow extends StatelessWidget {
  final String label;
  final String desc;
  final bool value;
  final ValueChanged<bool> onChanged;
  const _ToggleRow({
    required this.label,
    required this.desc,
    required this.value,
    required this.onChanged,
  });
  @override
  Widget build(BuildContext context) => Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(label,
                  style: TextStyle(
                      color: AppColors.ink, fontSize: 14.5, fontWeight: FontWeight.w700)),
              const SizedBox(height: 3),
              Text(desc,
                  style: TextStyle(color: AppColors.muted, fontSize: 12, height: 1.4)),
            ]),
          ),
          const SizedBox(width: 12),
          Switch(
            value: value,
            onChanged: onChanged,
            activeColor: const Color(0xFF141A08),
            activeTrackColor: AppColors.lime,
          ),
        ],
      );
}

class _Btn extends StatelessWidget {
  final String text;
  final bool primary;
  final VoidCallback onTap;
  const _Btn(this.text, {required this.onTap, this.primary = false});
  @override
  Widget build(BuildContext context) => GestureDetector(
        onTap: onTap,
        child: Container(
          alignment: Alignment.center,
          padding: const EdgeInsets.symmetric(vertical: 11, horizontal: 12),
          decoration: BoxDecoration(
            color: primary ? AppColors.lime : Colors.transparent,
            borderRadius: BorderRadius.circular(11),
            border: primary ? null : Border.all(color: AppColors.line),
          ),
          child: Text(text,
              style: TextStyle(
                  color: primary ? const Color(0xFF141A08) : AppColors.ink,
                  fontSize: 13,
                  fontWeight: FontWeight.w800)),
        ),
      );
}
