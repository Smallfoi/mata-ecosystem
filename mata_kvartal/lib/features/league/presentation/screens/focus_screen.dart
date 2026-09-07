import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../../core/theme/app_colors.dart';
import '../../data/league_provider.dart';

/// «Зачем ты бегаешь» — вопрос при первом запуске.
///
/// Гибкость без этого вопроса превращается в кашу: пять зачётов, территории,
/// тропы и клубы разом новичок не осилит. Ответ решает, что человек увидит
/// первым; остальное никуда не девается и включается в настройках.
///
/// Вопрос можно пропустить. Заставлять отвечать на входе нельзя — часть людей
/// просто закроет приложение.
class FocusScreen extends ConsumerStatefulWidget {
  const FocusScreen({super.key});

  @override
  ConsumerState<FocusScreen> createState() => _FocusScreenState();
}

class _FocusScreenState extends ConsumerState<FocusScreen> {
  String? _picked;
  bool _saving = false;

  Future<void> _save(String? focus) async {
    if (_saving) return;
    setState(() => _saving = true);
    try {
      if (focus != null) {
        await saveRunnerProfile(ref, focus: focus);
      } else {
        // Пропустил — запоминаем это как ответ «пока не решил»: иначе вопрос
        // будет всплывать при каждом запуске и раздражать.
        await saveRunnerProfile(ref, focus: 'skip');
      }
    } catch (_) {
      // Нет сети — не держим человека на этом экране: спросим в другой раз.
    }
    if (!mounted) return;
    context.go(_startRoute(focus));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.bg,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 24, 20, 20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Зачем ты бегаешь?',
                style: Theme.of(context).textTheme.headlineMedium
                    ?.copyWith(fontWeight: FontWeight.w800, height: 1.1),
              ),
              const SizedBox(height: 8),
              Text(
                'Соберём главный экран под твой ответ. Остальное никуда не денется — '
                'включишь в настройках, когда захочешь.',
                style: TextStyle(fontSize: 15, color: AppColors.muted, height: 1.45),
              ),
              const SizedBox(height: 22),
              Expanded(
                child: ListView.separated(
                  itemCount: _options.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 10),
                  itemBuilder: (_, i) {
                    final o = _options[i];
                    final active = _picked == o.key;
                    return GestureDetector(
                      onTap: () => setState(() => _picked = o.key),
                      child: AnimatedContainer(
                        duration: const Duration(milliseconds: 160),
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(
                          color: active ? AppColors.soft : AppColors.panel,
                          borderRadius: BorderRadius.circular(14),
                          border: Border.all(
                            color: active ? AppColors.accent : AppColors.separator,
                            width: active ? 1.5 : 1,
                          ),
                        ),
                        child: Row(
                          children: [
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    o.title,
                                    style: const TextStyle(
                                      fontSize: 17,
                                      fontWeight: FontWeight.w700,
                                    ),
                                  ),
                                  const SizedBox(height: 4),
                                  Text(
                                    o.hint,
                                    style: TextStyle(
                                      fontSize: 14,
                                      color: AppColors.muted,
                                      height: 1.4,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            if (active)
                              Icon(Icons.check_circle, color: AppColors.accentInk),
                          ],
                        ),
                      ),
                    );
                  },
                ),
              ),
              const SizedBox(height: 14),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: _picked == null || _saving ? null : () => _save(_picked),
                  child: Text(_saving ? 'Сохраняем…' : 'Продолжить'),
                ),
              ),
              TextButton(
                onPressed: _saving ? null : () => _save(null),
                child: const Text('Пропустить'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Куда попадает человек после ответа. Это и есть «главный экран под твой ответ»:
/// не перестройка интерфейса, а первое, что он видит.
String _startRoute(String? focus) => switch (focus) {
  'compete' => '/league',
  'social' => '/club',
  'health' || 'calm' => '/run',
  _ => '/map',
};

class _Option {
  final String key;
  final String title;
  final String hint;
  const _Option(this.key, this.title, this.hint);
}

const _options = <_Option>[
  _Option('health', 'Для здоровья',
      'Нагрузка, пульс, «сегодня лучше отдохнуть». Начнём с экрана пробежки.'),
  _Option('compete', 'Соревноваться',
      'Зачёты, рекорды, места в таблице. Откроем лигу — их там пять, и в каждой свой победитель.'),
  _Option('social', 'С людьми',
      'Клуб, общий зачёт, совместные пробежки. Начнём с клуба.'),
  _Option('calm', 'Разгрузить голову',
      'Бег без гонки за цифрами. Территории и рейтинги уберём с первого плана.'),
];
